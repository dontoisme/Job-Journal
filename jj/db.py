"""Database operations for Job Journal."""

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Optional

from jj.config import DB_PATH, JJ_HOME

# Application lifecycle status constants
ACTIVE_STATUSES = {
    'prospect',           # Identified, not yet applied
    'applied',            # Application submitted
    'recruiter_screen',   # Initial recruiter contact/screen
    'hiring_manager',     # HM screen or conversation
    'interview',          # Full interview loop
    'technical',          # Technical assessment
    'offer',              # Offer extended
}

TERMINAL_STATUSES = {'accepted', 'rejected', 'withdrawn'}

ALL_STATUSES = ACTIVE_STATUSES | TERMINAL_STATUSES

# Status ordering for progression tracking
STATUS_ORDER = {
    'prospect': 0,
    'applied': 1,
    'recruiter_screen': 2,
    'hiring_manager': 3,
    'interview': 4,
    'technical': 4,  # Same level as interview
    'offer': 5,
    'accepted': 6,
    'rejected': -1,
    'withdrawn': -1,
    'skipped': -2,
}

# Map email resolution types to application statuses
RESOLUTION_TO_STATUS = {
    'rejection': 'rejected',
    'screening': 'recruiter_screen',
    'interview': 'interview',
    'offer': 'offer',
}

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
    posted_at TEXT,                  -- Date job was originally posted (YYYY-MM-DD when available)
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

-- Target companies for job hunting
CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Core Identity
    name TEXT NOT NULL,                    -- Canonical company name
    name_normalized TEXT,                  -- LOWER(TRIM(name)) for matching
    aliases TEXT,                          -- JSON array of alternate spellings

    -- Job Board Tracking
    careers_url TEXT,                      -- Primary careers/jobs page URL
    ats_type TEXT,                         -- 'greenhouse', 'lever', 'ashby', 'workday', etc.

    -- Search Activity
    times_searched INTEGER DEFAULT 0,      -- Times we've searched this company
    last_searched_at TEXT,

    -- Contact Info (consolidated from applications)
    employer_phone TEXT,
    employer_address TEXT,
    employer_city TEXT,
    employer_state TEXT,
    employer_zip TEXT,
    contact_name TEXT,
    contact_email TEXT,

    -- Company Details
    website TEXT,
    industry TEXT,
    company_size TEXT,                     -- 'startup', 'small', 'medium', 'large', 'enterprise'

    -- Link to geo_companies (optional)
    geo_company_id INTEGER REFERENCES geo_companies(id),

    -- Hunting Status
    is_target BOOLEAN DEFAULT 1,           -- Active target for hunting
    target_priority INTEGER DEFAULT 0,     -- 1=high, 0=normal, -1=low
    notes TEXT,

    -- Timestamps
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
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

-- Companies indexes
CREATE UNIQUE INDEX IF NOT EXISTS idx_companies_name_normalized ON companies(name_normalized);
CREATE INDEX IF NOT EXISTS idx_companies_target ON companies(is_target, target_priority DESC);

-- TWC payment request tracking
CREATE TABLE IF NOT EXISTS twc_payment_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    week_start TEXT NOT NULL UNIQUE,    -- Sunday date (YYYY-MM-DD)
    submitted BOOLEAN DEFAULT 0,
    submitted_at TEXT,
    activities_reported INTEGER,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Personal interests for cover letter hooks
CREATE TABLE IF NOT EXISTS interests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT NOT NULL,
    story TEXT,
    tags TEXT,                          -- JSON array: ["gaming", "ai", "interactive"]
    connection TEXT,                    -- Professional bridge sentence
    times_used INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Generated cover letters
CREATE TABLE IF NOT EXISTS cover_letters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT UNIQUE NOT NULL,
    filepath TEXT,
    target_company TEXT,
    target_role TEXT,
    interest_id INTEGER,
    google_doc_id TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (interest_id) REFERENCES interests(id)
);

CREATE INDEX IF NOT EXISTS idx_interests_topic ON interests(topic);
CREATE INDEX IF NOT EXISTS idx_cover_letters_company ON cover_letters(target_company);

-- Monitor run history
CREATE TABLE IF NOT EXISTS monitor_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_type TEXT NOT NULL,               -- 'full', 'companies', 'boards'
    started_at TEXT DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    companies_checked INTEGER DEFAULT 0,
    boards_checked INTEGER DEFAULT 0,
    new_listings_found INTEGER DEFAULT 0,
    notification_sent BOOLEAN DEFAULT 0,
    summary TEXT,                          -- JSON
    error_log TEXT                         -- JSON
);
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
        # Company foreign key for applications
        ("applications", "company_id", "INTEGER REFERENCES companies(id)"),
        # Company contact columns (may have been missed in initial schema)
        ("companies", "contact_name", "TEXT"),
        ("companies", "contact_email", "TEXT"),
        # Company fit scoring
        ("companies", "fit_score", "INTEGER"),
        ("companies", "fit_notes", "TEXT"),
        # Job posting date
        ("applications", "posted_at", "TEXT"),
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

        -- Target companies for job hunting
        CREATE TABLE IF NOT EXISTS companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            name_normalized TEXT,
            aliases TEXT,
            careers_url TEXT,
            ats_type TEXT,
            times_searched INTEGER DEFAULT 0,
            last_searched_at TEXT,
            employer_phone TEXT,
            employer_address TEXT,
            employer_city TEXT,
            employer_state TEXT,
            employer_zip TEXT,
            contact_name TEXT,
            contact_email TEXT,
            website TEXT,
            industry TEXT,
            company_size TEXT,
            geo_company_id INTEGER REFERENCES geo_companies(id),
            is_target BOOLEAN DEFAULT 1,
            target_priority INTEGER DEFAULT 0,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_companies_name_normalized ON companies(name_normalized);
        CREATE INDEX IF NOT EXISTS idx_companies_target ON companies(is_target, target_priority DESC);

        -- Personal interests for cover letter hooks
        CREATE TABLE IF NOT EXISTS interests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT NOT NULL,
            story TEXT,
            tags TEXT,
            connection TEXT,
            times_used INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        -- Generated cover letters
        CREATE TABLE IF NOT EXISTS cover_letters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT UNIQUE NOT NULL,
            filepath TEXT,
            target_company TEXT,
            target_role TEXT,
            interest_id INTEGER,
            google_doc_id TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (interest_id) REFERENCES interests(id)
        );

        CREATE INDEX IF NOT EXISTS idx_interests_topic ON interests(topic);
        CREATE INDEX IF NOT EXISTS idx_cover_letters_company ON cover_letters(target_company);

        -- Job listings for delta detection (swarm monitoring)
        CREATE TABLE IF NOT EXISTS job_listings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL REFERENCES companies(id),
            url TEXT NOT NULL,
            title TEXT,
            location TEXT,
            salary TEXT,
            ats_type TEXT,
            is_active BOOLEAN DEFAULT 1,
            first_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
            last_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
            scored_at TEXT,
            application_id INTEGER REFERENCES applications(id),
            UNIQUE(company_id, url)
        );
        CREATE INDEX IF NOT EXISTS idx_job_listings_company ON job_listings(company_id, is_active);
        CREATE INDEX IF NOT EXISTS idx_job_listings_url ON job_listings(url);
        CREATE INDEX IF NOT EXISTS idx_job_listings_first_seen ON job_listings(first_seen_at);

        -- Investor/VC job boards (aggregators listing jobs across portfolio companies)
        CREATE TABLE IF NOT EXISTS investor_boards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            name_normalized TEXT,
            short_name TEXT,
            board_url TEXT,
            ats_type TEXT,
            board_type TEXT DEFAULT 'vc',
            investor_type TEXT,
            has_talent_network BOOLEAN DEFAULT 0,
            talent_network_url TEXT,
            talent_network_notes TEXT,
            portfolio_focus TEXT,
            geo_focus TEXT,
            times_searched INTEGER DEFAULT 0,
            last_searched_at TEXT,
            job_count INTEGER DEFAULT 0,
            is_active BOOLEAN DEFAULT 1,
            priority INTEGER DEFAULT 0,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_investor_boards_name ON investor_boards(name_normalized);
        CREATE INDEX IF NOT EXISTS idx_investor_boards_active ON investor_boards(is_active, priority DESC);

        CREATE TABLE IF NOT EXISTS investor_board_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            investor_board_id INTEGER NOT NULL REFERENCES investor_boards(id),
            company_id INTEGER REFERENCES companies(id),
            url TEXT NOT NULL,
            title TEXT,
            company_name TEXT,
            location TEXT,
            salary TEXT,
            is_active BOOLEAN DEFAULT 1,
            first_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
            last_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(investor_board_id, url)
        );
        CREATE INDEX IF NOT EXISTS idx_investor_board_jobs_board ON investor_board_jobs(investor_board_id, is_active);
        """
        conn.executescript(new_tables_sql)
        conn.commit()

        # Create index on company_id after column migration (may not exist yet)
        try:
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_applications_company_id ON applications(company_id)")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # Column doesn't exist yet

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


def migrate_application_lifecycle() -> dict[str, int]:
    """
    Migrate application statuses to use the new lifecycle model.

    1. Rename 'screening' → 'recruiter_screen'
    2. Create initial status_change events for applications without history

    Returns dict with counts: {renamed: N, events_created: N}
    """
    results = {'renamed': 0, 'events_created': 0}

    with get_connection() as conn:
        cursor = conn.cursor()

        # Step 1: Rename 'screening' to 'recruiter_screen'
        cursor.execute("""
            UPDATE applications
            SET status = 'recruiter_screen'
            WHERE status = 'screening'
        """)
        results['renamed'] = cursor.rowcount
        conn.commit()

        # Step 2: Create initial events for applications without event history
        cursor.execute("""
            INSERT INTO events (event_type, entity_type, entity_id, old_value, new_value, metadata, created_at)
            SELECT
                'status_change',
                'application',
                id,
                json_object('status', NULL),
                json_object('status', status),
                json_object('source', 'migration', 'reason', 'Initial state from migration'),
                COALESCE(applied_at, created_at)
            FROM applications
            WHERE id NOT IN (
                SELECT DISTINCT entity_id
                FROM events
                WHERE event_type = 'status_change' AND entity_type = 'application'
            )
        """)
        results['events_created'] = cursor.rowcount
        conn.commit()

    return results


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

def _normalize_title(title: str) -> str:
    """Normalize a job title for dedup comparison."""
    t = title.lower().strip()
    # Normalize PM variants
    for long, short in [
        ("product manager", "pm"),
        ("product management", "pm"),
        ("senior ", "sr "),
    ]:
        t = t.replace(long, short)
    # Strip punctuation and extra spaces
    t = re.sub(r"[,\-–—()/]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def find_duplicate_application(
    company: str,
    position: str,
    job_url: str = None,
) -> Optional[dict[str, Any]]:
    """Check if an application already exists for this company+role.

    Checks:
    1. Exact URL match
    2. Normalized company + title match (handles PM vs Product Manager, etc.)

    Returns the existing application dict or None.
    """
    with get_connection() as conn:
        cursor = conn.cursor()

        # 1. Exact URL match
        if job_url:
            cursor.execute(
                "SELECT * FROM applications WHERE job_url = ?", (job_url,)
            )
            row = cursor.fetchone()
            if row:
                return dict(row)

        # 2. Normalized title match within same company
        norm_title = _normalize_title(position)
        cursor.execute(
            "SELECT * FROM applications WHERE LOWER(TRIM(company)) = ?",
            (company.lower().strip(),)
        )
        for row in cursor.fetchall():
            existing_norm = _normalize_title(row["position"])
            # Check if titles are substantially similar (one contains the other,
            # or they share the first 20 chars after normalization)
            if (norm_title == existing_norm
                    or norm_title in existing_norm
                    or existing_norm in norm_title
                    or norm_title[:20] == existing_norm[:20]):
                return dict(row)

        return None


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


def transition_application_status(
    app_id: int,
    new_status: str,
    reason: Optional[str] = None,
    source: str = 'manual',
    metadata: Optional[dict] = None,
) -> bool:
    """
    Update application status and log event atomically.

    This is the ONLY function that should change application status to ensure
    all transitions are tracked in the events table.

    Args:
        app_id: Application ID to update
        new_status: New status value (must be in ALL_STATUSES or 'skipped')
        reason: Human-readable reason for the change (e.g., "Email resolution: rejection")
        source: Source of the change ('manual', 'email', 'api')
        metadata: Additional context (e.g., {email_id: ...})

    Returns:
        True if successful, False otherwise
    """
    # Validate new_status
    valid_statuses = ALL_STATUSES | {'skipped', 'screening'}  # Include screening for backward compat
    if new_status not in valid_statuses:
        return False

    # Get current status
    app = get_application(app_id)
    if not app:
        return False

    old_status = app.get('status')

    # Don't log if status hasn't changed
    if old_status == new_status:
        return True

    # Update the status
    success = update_application(app_id, status=new_status)
    if not success:
        return False

    # Log the event
    log_event(
        event_type='status_change',
        entity_type='application',
        entity_id=app_id,
        old_value={'status': old_status},
        new_value={'status': new_status},
        metadata={
            'reason': reason,
            'source': source,
            **(metadata or {}),
        }
    )

    return True


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


def get_resumes_with_applications(days: int = 30) -> list[dict]:
    """Get resumes joined with application data, ordered by date desc.

    Joins on resume_id FK first, falls back to company name match.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                r.id as resume_id,
                r.target_company as company,
                r.target_role as position,
                r.variant,
                r.google_doc_id,
                r.filepath as pdf_path,
                r.created_at,
                r.rj_score,
                COALESCE(a_fk.id, a_name.id) as application_id,
                COALESCE(a_fk.fit_score, a_name.fit_score) as fit_score,
                COALESCE(a_fk.rj_before, a_name.rj_before) as rj_before,
                COALESCE(a_fk.rj_after, a_name.rj_after) as rj_after,
                COALESCE(a_fk.status, a_name.status) as status,
                COALESCE(a_fk.job_url, a_name.job_url) as job_url,
                COALESCE(a_fk.location, a_name.location) as location,
                COALESCE(a_fk.notes, a_name.notes) as notes
            FROM resumes r
            LEFT JOIN applications a_fk ON a_fk.resume_id = r.id
            LEFT JOIN applications a_name
                ON a_fk.id IS NULL
                AND LOWER(a_name.company) = LOWER(r.target_company)
                AND a_name.id = (
                    SELECT MAX(a2.id) FROM applications a2
                    WHERE LOWER(a2.company) = LOWER(r.target_company)
                )
            WHERE r.created_at >= datetime('now', ?)
            ORDER BY r.created_at DESC
            """,
            (f"-{days} days",)
        )
        return [dict(row) for row in cursor.fetchall()]


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


# Interest operations (for cover letter hooks)

def create_interest(
    topic: str,
    story: Optional[str] = None,
    tags: Optional[list[str]] = None,
    connection: Optional[str] = None,
) -> int:
    """Create an interest and return its ID."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO interests (topic, story, tags, connection)
            VALUES (?, ?, ?, ?)
            """,
            (topic, story, json.dumps(tags or []), connection)
        )
        conn.commit()
        return cursor.lastrowid


def get_interests() -> list[dict[str, Any]]:
    """Get all interests ordered by most used first."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM interests ORDER BY times_used DESC, topic")
        return [dict(row) for row in cursor.fetchall()]


def get_interests_by_tags(tags: list[str]) -> list[dict[str, Any]]:
    """Get interests matching any of the given tags (least used first for variety)."""
    if not tags:
        return []
    with get_connection() as conn:
        cursor = conn.cursor()
        conditions = " OR ".join(["tags LIKE ?" for _ in tags])
        params = [f'%"{tag}"%' for tag in tags]
        cursor.execute(
            f"SELECT * FROM interests WHERE {conditions} ORDER BY times_used ASC, id",
            params
        )
        return [dict(row) for row in cursor.fetchall()]


def update_interest(interest_id: int, **kwargs) -> bool:
    """Update interest fields. Returns True if successful."""
    if not kwargs:
        return False
    with get_connection() as conn:
        cursor = conn.cursor()
        if "tags" in kwargs and isinstance(kwargs["tags"], list):
            kwargs["tags"] = json.dumps(kwargs["tags"])
        set_clause = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [interest_id]
        cursor.execute(
            f"UPDATE interests SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            values,
        )
        conn.commit()
        return cursor.rowcount > 0


def increment_interest_usage(interest_id: int) -> bool:
    """Increment times_used for an interest."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE interests SET times_used = times_used + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (interest_id,),
        )
        conn.commit()
        return cursor.rowcount > 0


# Cover letter operations

def create_cover_letter(
    filename: str,
    filepath: Optional[str] = None,
    target_company: Optional[str] = None,
    target_role: Optional[str] = None,
    interest_id: Optional[int] = None,
    google_doc_id: Optional[str] = None,
) -> int:
    """Create a cover letter record and return its ID."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO cover_letters (filename, filepath, target_company, target_role, interest_id, google_doc_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (filename, filepath, target_company, target_role, interest_id, google_doc_id),
        )
        conn.commit()
        return cursor.lastrowid


def get_cover_letters(company: Optional[str] = None, limit: int = 50) -> list[dict[str, Any]]:
    """Get cover letters, optionally filtered by company."""
    with get_connection() as conn:
        cursor = conn.cursor()
        if company:
            cursor.execute(
                "SELECT * FROM cover_letters WHERE target_company = ? ORDER BY created_at DESC LIMIT ?",
                (company, limit),
            )
        else:
            cursor.execute(
                "SELECT * FROM cover_letters ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        return [dict(row) for row in cursor.fetchall()]


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


def get_twc_claim_period(week_start: Optional[str] = None) -> dict[str, Any]:
    """
    Get a TWC biweekly claim period summary.
    TWC claim periods are two consecutive Sun-Sat weeks.
    Returns summaries for both weeks plus payment submission status.
    """
    from datetime import timedelta

    # Get the first week's boundaries
    sunday1, saturday1 = get_twc_week_boundaries(week_start)
    start1 = datetime.strptime(sunday1, "%Y-%m-%d")

    # Second week is the next Sun-Sat
    start2 = start1 + timedelta(days=7)
    sunday2 = start2.strftime("%Y-%m-%d")

    # Get summaries for both weeks
    summary1 = get_twc_week_summary(sunday1)
    summary2 = get_twc_week_summary(sunday2)

    # Get payment submission status for each week
    payment1 = get_twc_payment_status(sunday1)
    payment2 = get_twc_payment_status(sunday2)

    return {
        'week1': {
            'start': sunday1,
            'end': saturday1,
            'display': f"{start1.strftime('%b %d')} - {datetime.strptime(saturday1, '%Y-%m-%d').strftime('%b %d, %Y')}",
            'summary': summary1,
            'payment': payment1,
        },
        'week2': {
            'start': sunday2,
            'end': (start2 + timedelta(days=6)).strftime("%Y-%m-%d"),
            'display': f"{start2.strftime('%b %d')} - {(start2 + timedelta(days=6)).strftime('%b %d, %Y')}",
            'summary': summary2,
            'payment': payment2,
        },
        'total_activities': summary1['total_activities'] + summary2['total_activities'],
        'period_display': f"{start1.strftime('%b %d')} - {(start2 + timedelta(days=6)).strftime('%b %d, %Y')}",
    }


def get_twc_payment_status(week_start: str) -> dict[str, Any]:
    """Get payment submission status for a specific week."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM twc_payment_requests WHERE week_start = ?",
            (week_start,)
        )
        row = cursor.fetchone()
        if row:
            return dict(row)
        return {'week_start': week_start, 'submitted': False, 'submitted_at': None, 'activities_reported': None}


def mark_twc_payment_submitted(week_start: str, submitted: bool, activities_reported: int = None) -> bool:
    """Mark a TWC week's payment request as submitted or not."""
    with get_connection() as conn:
        cursor = conn.cursor()
        if submitted:
            cursor.execute("""
                INSERT INTO twc_payment_requests (week_start, submitted, submitted_at, activities_reported)
                VALUES (?, 1, ?, ?)
                ON CONFLICT(week_start) DO UPDATE SET
                    submitted = 1,
                    submitted_at = excluded.submitted_at,
                    activities_reported = excluded.activities_reported
            """, (week_start, datetime.now().isoformat(), activities_reported))
        else:
            cursor.execute("""
                INSERT INTO twc_payment_requests (week_start, submitted)
                VALUES (?, 0)
                ON CONFLICT(week_start) DO UPDATE SET
                    submitted = 0,
                    submitted_at = NULL
            """, (week_start,))
        conn.commit()
        return True


def get_all_twc_claim_periods() -> list[dict[str, Any]]:
    """
    Get all TWC biweekly claim periods from earliest activity to current week.
    Uses batch queries for efficiency (3 queries total, not N).
    Returns list of period dicts, newest first.
    """
    from collections import defaultdict
    from datetime import timedelta

    with get_connection() as conn:
        cursor = conn.cursor()

        # Query 1: Find earliest activity date
        cursor.execute("""
            SELECT MIN(COALESCE(activity_date, DATE(applied_at), DATE(created_at))) as earliest
            FROM applications
            WHERE status NOT IN ('prospect', 'skipped')
        """)
        row = cursor.fetchone()
        earliest = row['earliest'] if row and row['earliest'] else None
        if not earliest:
            return []

        # Query 2: Get all activity counts grouped by week Sunday
        cursor.execute("""
            SELECT
                COALESCE(activity_date, DATE(applied_at), DATE(created_at)) as effective_date
            FROM applications
            WHERE status NOT IN ('prospect', 'skipped')
              AND COALESCE(activity_date, DATE(applied_at), DATE(created_at)) IS NOT NULL
            ORDER BY effective_date
        """)
        activities = cursor.fetchall()

        # Query 3: Get all payment statuses
        cursor.execute("SELECT * FROM twc_payment_requests")
        payment_rows = cursor.fetchall()

    # Build payment lookup
    payment_lookup = {}
    for p in payment_rows:
        p = dict(p)
        payment_lookup[p['week_start']] = p

    # Bucket activities by their week Sunday
    counts_by_sunday = defaultdict(int)
    for act in activities:
        d = datetime.strptime(act['effective_date'], "%Y-%m-%d")
        days_since_sunday = (d.weekday() + 1) % 7
        sunday = d - timedelta(days=days_since_sunday)
        counts_by_sunday[sunday.strftime("%Y-%m-%d")] += 1

    # Align to TWC's fixed biweekly claim period calendar.
    # TWC uses a fixed epoch -- Jan 4, 2026 is a known period start (Sunday).
    # All periods are 14-day multiples from this epoch.
    twc_epoch = datetime(2026, 1, 4)

    earliest_dt = datetime.strptime(earliest, "%Y-%m-%d")
    days_since_sunday = (earliest_dt.weekday() + 1) % 7
    first_sunday = earliest_dt - timedelta(days=days_since_sunday)

    today = datetime.now()
    days_since_sunday = (today.weekday() + 1) % 7
    current_sunday = today - timedelta(days=days_since_sunday)

    # Find the TWC period that contains the earliest activity
    days_from_epoch = (first_sunday - twc_epoch).days
    # Align to nearest period boundary (can be negative if before epoch)
    period_offset = days_from_epoch % 14
    period_start = first_sunday - timedelta(days=period_offset)

    # Build periods (step by 14 days)
    periods = []
    while period_start <= current_sunday:
        week1_start = period_start
        week1_end = week1_start + timedelta(days=6)
        week2_start = period_start + timedelta(days=7)
        week2_end = week2_start + timedelta(days=6)

        w1_str = week1_start.strftime("%Y-%m-%d")
        w2_str = week2_start.strftime("%Y-%m-%d")

        w1_count = counts_by_sunday.get(w1_str, 0)
        w2_count = counts_by_sunday.get(w2_str, 0)

        w1_payment = payment_lookup.get(w1_str, {
            'week_start': w1_str, 'submitted': False, 'submitted_at': None, 'activities_reported': None
        })
        w2_payment = payment_lookup.get(w2_str, {
            'week_start': w2_str, 'submitted': False, 'submitted_at': None, 'activities_reported': None
        })

        periods.append({
            'week1': {
                'start': w1_str,
                'end': week1_end.strftime("%Y-%m-%d"),
                'display': f"{week1_start.strftime('%b %d')} - {week1_end.strftime('%b %d, %Y')}",
                'activity_count': w1_count,
                'is_complete': w1_count >= 3,
                'payment': w1_payment,
            },
            'week2': {
                'start': w2_str,
                'end': week2_end.strftime("%Y-%m-%d"),
                'display': f"{week2_start.strftime('%b %d')} - {week2_end.strftime('%b %d, %Y')}",
                'activity_count': w2_count,
                'is_complete': w2_count >= 3,
                'payment': w2_payment,
            },
            'total_activities': w1_count + w2_count,
            'period_display': f"{week1_start.strftime('%b %d')} - {week2_end.strftime('%b %d, %Y')}",
        })

        period_start += timedelta(days=14)

    # Return newest first
    periods.reverse()
    return periods


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


# =============================================================================
# Company Functions
# =============================================================================


def get_or_create_company(name: str, **kwargs) -> int:
    """
    Get existing company by name or create new one.
    Returns company ID.
    """
    normalized = name.lower().strip()

    with get_connection() as conn:
        cursor = conn.cursor()

        # Try to find existing
        cursor.execute(
            "SELECT id FROM companies WHERE name_normalized = ?",
            (normalized,)
        )
        row = cursor.fetchone()

        if row:
            return row['id']

        # Create new company
        cursor.execute("""
            INSERT INTO companies (name, name_normalized, careers_url, ats_type, website)
            VALUES (?, ?, ?, ?, ?)
        """, (
            name,
            normalized,
            kwargs.get('careers_url'),
            kwargs.get('ats_type'),
            kwargs.get('website'),
        ))
        conn.commit()
        return cursor.lastrowid


def find_company_by_name(name: str, fuzzy: bool = False) -> Optional[dict[str, Any]]:
    """
    Find company by name. Optionally use fuzzy matching.
    """
    normalized = name.lower().strip()

    with get_connection() as conn:
        cursor = conn.cursor()

        # Exact match first
        cursor.execute(
            "SELECT * FROM companies WHERE name_normalized = ?",
            (normalized,)
        )
        row = cursor.fetchone()
        if row:
            return dict(row)

        # Check aliases
        cursor.execute("""
            SELECT * FROM companies
            WHERE aliases LIKE ?
        """, (f'%"{normalized}"%',))
        row = cursor.fetchone()
        if row:
            return dict(row)

        # Fuzzy match if requested
        if fuzzy:
            cursor.execute("""
                SELECT * FROM companies
                WHERE name_normalized LIKE ?
                ORDER BY LENGTH(name_normalized) ASC
                LIMIT 1
            """, (f'%{normalized}%',))
            row = cursor.fetchone()
            if row:
                return dict(row)

        return None


def get_company(company_id: int) -> Optional[dict[str, Any]]:
    """Get a company by ID."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM companies WHERE id = ?", (company_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def update_company(company_id: int, **kwargs) -> bool:
    """Update a company record."""
    if not kwargs:
        return False

    with get_connection() as conn:
        cursor = conn.cursor()

        # Build SET clause
        set_parts = [f"{k} = ?" for k in kwargs.keys()]
        set_parts.append("updated_at = CURRENT_TIMESTAMP")
        values = list(kwargs.values()) + [company_id]

        cursor.execute(
            f"UPDATE companies SET {', '.join(set_parts)} WHERE id = ?",
            values
        )
        conn.commit()
        return cursor.rowcount > 0


def add_company_alias(company_id: int, alias: str) -> bool:
    """Add an alternate name/spelling for a company."""
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT aliases FROM companies WHERE id = ?", (company_id,))
        row = cursor.fetchone()
        if not row:
            return False

        aliases = json.loads(row['aliases'] or '[]')
        normalized_alias = alias.lower().strip()

        if normalized_alias not in aliases:
            aliases.append(normalized_alias)
            cursor.execute(
                "UPDATE companies SET aliases = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (json.dumps(aliases), company_id)
            )
            conn.commit()

        return True


def increment_search_count(company_id: int) -> None:
    """Increment search count for a company."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE companies
            SET times_searched = times_searched + 1,
                last_searched_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (company_id,))
        conn.commit()


def update_company_fit(company_id: int, fit_score: int, fit_notes: str = None) -> bool:
    """Update company fit score and notes."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE companies
            SET fit_score = ?,
                fit_notes = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (fit_score, fit_notes, company_id))
        conn.commit()
        return cursor.rowcount > 0


def get_all_companies() -> list[dict[str, Any]]:
    """Get all companies."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM companies ORDER BY name")
        return [dict(row) for row in cursor.fetchall()]


def get_target_companies(priority: Optional[int] = None) -> list[dict[str, Any]]:
    """Get companies marked as hunting targets with application counts."""
    with get_connection() as conn:
        cursor = conn.cursor()

        query = """
            SELECT
                c.*,
                COUNT(a.id) as application_count,
                SUM(CASE WHEN a.status NOT IN ('rejected', 'withdrawn', 'prospect') THEN 1 ELSE 0 END) as active_count,
                MAX(a.applied_at) as latest_applied_at
            FROM companies c
            LEFT JOIN applications a ON a.company_id = c.id
            WHERE c.is_target = 1
        """

        if priority is not None:
            query += " AND c.target_priority = ?"
            query += " GROUP BY c.id ORDER BY c.fit_score DESC NULLS LAST, c.target_priority DESC, c.name"
            cursor.execute(query, (priority,))
        else:
            query += " GROUP BY c.id ORDER BY c.fit_score DESC NULLS LAST, c.target_priority DESC, c.name"
            cursor.execute(query)

        return [dict(row) for row in cursor.fetchall()]


def get_companies_with_applications() -> list[dict[str, Any]]:
    """Get companies that have applications with counts."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                c.*,
                COUNT(a.id) as application_count,
                SUM(CASE WHEN a.status NOT IN ('rejected', 'withdrawn', 'prospect') THEN 1 ELSE 0 END) as active_count,
                MAX(a.applied_at) as latest_applied_at
            FROM companies c
            INNER JOIN applications a ON a.company_id = c.id
            GROUP BY c.id
            HAVING application_count > 0
            ORDER BY application_count DESC, c.name
        """)
        return [dict(row) for row in cursor.fetchall()]


def detect_ats_type(job_url: str) -> Optional[str]:
    """Detect ATS type from job URL."""
    if not job_url:
        return None

    url_lower = job_url.lower()
    if 'greenhouse' in url_lower:
        return 'greenhouse'
    elif 'lever.co' in url_lower:
        return 'lever'
    elif 'ashby' in url_lower:
        return 'ashby'
    elif 'workday' in url_lower:
        return 'workday'
    elif 'icims' in url_lower:
        return 'icims'
    elif 'rippling' in url_lower:
        return 'rippling'
    elif 'jobvite' in url_lower:
        return 'jobvite'
    elif 'smartrecruiters' in url_lower:
        return 'smartrecruiters'
    return None


def score_title_fit(title: str, location: str = None) -> dict[str, Any]:
    """Quick title + location pre-filter before expensive JD scoring.

    Returns dict with total score (0-100), breakdown, and pass/fail.
    Threshold: 50+ proceeds to full JD scoring.
    """
    title_lower = (title or "").lower()
    loc_lower = (location or "").lower()

    # --- Seniority (0-40) ---
    seniority = 0
    seniority_label = "unknown"
    if any(k in title_lower for k in ["head of", "vp ", "vice president", "chief product"]):
        seniority, seniority_label = 40, "executive"
    elif any(k in title_lower for k in ["director", "sr director", "senior director"]):
        seniority, seniority_label = 40, "director"
    elif any(k in title_lower for k in ["principal", "staff"]):
        seniority, seniority_label = 40, "principal/staff"
    elif any(k in title_lower for k in ["senior ", "sr ", "lead "]):
        seniority, seniority_label = 30, "senior"
    elif any(k in title_lower for k in ["product manager", "product lead"]):
        seniority, seniority_label = 15, "mid-level"
    elif any(k in title_lower for k in [" ii", " iii", " iv"]):
        seniority, seniority_label = 15, "mid-level"

    # --- Role type (0-30) ---
    role_type = 0
    role_label = "other"
    if any(k in title_lower for k in ["product manager", "product management", "product lead",
                                       "head of product", "director of product", "vp product",
                                       "chief product", "product director"]):
        role_type, role_label = 30, "product management"
    elif any(k in title_lower for k in [" pm,", " pm ", " pm-", "sr pm", "staff pm",
                                         "principal pm"]):
        role_type, role_label = 30, "product management"
    elif "growth" in title_lower and "product" in title_lower:
        role_type, role_label = 30, "growth PM"
    elif "growth" in title_lower:
        role_type, role_label = 25, "growth"
    elif any(k in title_lower for k in ["strategy & operations", "strategy and operations",
                                         "strategic program"]):
        role_type, role_label = 15, "strategy/ops"
    elif "program manager" in title_lower:
        role_type, role_label = 10, "program management"
    elif "product marketing" in title_lower:
        role_type, role_label = 5, "product marketing"
    elif "data analyst" in title_lower or "data scientist" in title_lower:
        role_type, role_label = 5, "data/analytics"
    elif "gtm" in title_lower:
        role_type, role_label = 10, "GTM"

    # --- Location (0-30) ---
    # Check international FIRST (hard fail — these never pass regardless of score)
    loc_score = 0
    loc_label = "unknown"
    is_international = False
    if location and any(k in loc_lower for k in [
        "london", "canada", "india", "ireland", "barcelona", "jordan", "uk,",
        "vancouver", "montreal", "gurgaon", "dublin", "auckland", "new zealand",
        "amman", "bangalore", "toronto", "germany", "france", "singapore",
        "australia", "brazil", "japan", "korea", "mexico", "argentina",
    ]):
        # But NOT international if also has US location (e.g., "Remote US / Toronto")
        has_us = any(k in loc_lower for k in ["austin", "remote us", "us remote",
                                               "u.s.", "san francisco", "new york",
                                               "nyc", "seattle", "chicago", "sf,",
                                               "sf /", "ssf", "bay area"])
        if not has_us:
            loc_score, loc_label = 0, "international"
            is_international = True

    if not is_international:
        if not location:
            loc_score, loc_label = 15, "not specified"
        elif any(k in loc_lower for k in ["austin", "remote us", "us remote", "remote - us",
                                           "u.s. remote", "remote united states"]):
            loc_score, loc_label = 30, "austin/remote US"
        elif "remote" in loc_lower and any(k in loc_lower for k in ["us", "u.s.", "united states"]):
            loc_score, loc_label = 30, "remote US"
        elif any(k in loc_lower for k in ["san francisco", "new york", "nyc", "sf "]):
            loc_score, loc_label = 20, "SF/NYC"
        elif any(k in loc_lower for k in ["seattle", "chicago", "oakland", "bay area"]):
            loc_score, loc_label = 15, "major US city"
        elif any(k in loc_lower for k in ["california", "texas", "san jose"]):
            loc_score, loc_label = 15, "US state"
        else:
            loc_score, loc_label = 10, "other US"

    total = seniority + role_type + loc_score
    return {
        "total": total,
        "pass": total >= 50 and not is_international,
        "seniority": {"score": seniority, "max": 40, "label": seniority_label},
        "role_type": {"score": role_type, "max": 30, "label": role_label},
        "location": {"score": loc_score, "max": 30, "label": loc_label},
    }


# Job listings operations (swarm monitoring)

def record_job_listing(company_id: int, url: str, title: str = None,
                       location: str = None, salary: str = None,
                       ats_type: str = None) -> tuple[int, bool]:
    """Record a job listing. Returns (listing_id, is_new).
    Uses INSERT OR IGNORE + UPDATE for upsert behavior."""
    with get_connection() as conn:
        cursor = conn.cursor()

        # Try insert first (will be ignored if url+company_id already exists)
        cursor.execute("""
            INSERT OR IGNORE INTO job_listings (company_id, url, title, location, salary, ats_type)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (company_id, url, title, location, salary, ats_type))

        is_new = cursor.rowcount > 0

        if not is_new:
            # Update last_seen and any new metadata
            cursor.execute("""
                UPDATE job_listings
                SET last_seen_at = CURRENT_TIMESTAMP,
                    is_active = 1,
                    title = COALESCE(?, title),
                    location = COALESCE(?, location),
                    salary = COALESCE(?, salary),
                    ats_type = COALESCE(?, ats_type)
                WHERE company_id = ? AND url = ?
            """, (title, location, salary, ats_type, company_id, url))

        conn.commit()

        cursor.execute(
            "SELECT id FROM job_listings WHERE company_id = ? AND url = ?",
            (company_id, url)
        )
        listing_id = cursor.fetchone()["id"]

        return (listing_id, is_new)


def is_known_job(url: str) -> Optional[dict[str, Any]]:
    """Check if a job URL has been seen before in job_listings OR applications.

    Returns dict with source info if known, None if never seen.
    Used by pipeline to skip jobs we've already scraped/filtered/scored.
    """
    if not url:
        return None
    with get_connection() as conn:
        # Check job_listings first (covers all scraped jobs including filtered ones)
        row = conn.execute(
            "SELECT id, company_id, title, first_seen_at, last_seen_at FROM job_listings WHERE url = ?",
            (url,)
        ).fetchone()
        if row:
            return {"source": "job_listings", "id": row["id"], "title": row["title"],
                    "first_seen": row["first_seen_at"], "last_seen": row["last_seen_at"]}

        # Check applications (covers jobs tracked as prospects/applied/etc)
        row = conn.execute(
            "SELECT id, company, position, status, fit_score FROM applications WHERE job_url = ?",
            (url,)
        ).fetchone()
        if row:
            return {"source": "applications", "id": row["id"], "company": row["company"],
                    "position": row["position"], "status": row["status"], "fit_score": row["fit_score"]}

    return None


def get_known_listing_urls(company_id: int) -> set[str]:
    """Get set of all known listing URLs for a company (active and inactive)."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT url FROM job_listings WHERE company_id = ?",
            (company_id,)
        )
        return {row["url"] for row in cursor.fetchall()}


def mark_stale_listings(company_id: int, active_urls: set[str]) -> int:
    """Mark listings NOT in active_urls as inactive. Returns count marked stale."""
    with get_connection() as conn:
        cursor = conn.cursor()

        if not active_urls:
            # Mark all as stale
            cursor.execute("""
                UPDATE job_listings SET is_active = 0
                WHERE company_id = ? AND is_active = 1
            """, (company_id,))
        else:
            placeholders = ",".join("?" for _ in active_urls)
            cursor.execute(f"""
                UPDATE job_listings SET is_active = 0
                WHERE company_id = ? AND is_active = 1 AND url NOT IN ({placeholders})
            """, (company_id, *active_urls))

        stale_count = cursor.rowcount
        conn.commit()
        return stale_count


def get_new_listings_since(company_id: int, since: str) -> list[dict]:
    """Get listings first seen after `since` timestamp (ISO format)."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM job_listings
            WHERE company_id = ? AND first_seen_at > ?
            ORDER BY first_seen_at DESC
        """, (company_id, since))
        return [dict(row) for row in cursor.fetchall()]


def get_companies_due_for_check(hours: int = 24) -> list[dict[str, Any]]:
    """Get target companies with careers_url not checked in the last N hours.
    Returns same shape as get_target_companies() but filtered by last_searched_at."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                c.*,
                COUNT(a.id) as application_count,
                SUM(CASE WHEN a.status NOT IN ('rejected', 'withdrawn', 'prospect') THEN 1 ELSE 0 END) as active_count,
                MAX(a.applied_at) as latest_applied_at
            FROM companies c
            LEFT JOIN applications a ON a.company_id = c.id
            WHERE c.is_target = 1
              AND c.careers_url IS NOT NULL
              AND (c.last_searched_at IS NULL
                   OR c.last_searched_at < datetime('now', ? || ' hours'))
            GROUP BY c.id
            ORDER BY c.fit_score DESC NULLS LAST, c.target_priority DESC, c.name
        """, (f"-{hours}",))
        return [dict(row) for row in cursor.fetchall()]


def migrate_companies_from_applications() -> dict[str, int]:
    """
    Create companies from existing application company names.
    Uses case-insensitive deduplication.
    Returns counts of companies created and applications linked.
    """
    with get_connection() as conn:
        cursor = conn.cursor()

        # Get unique companies with aggregated data
        cursor.execute("""
            SELECT
                company,
                LOWER(TRIM(company)) as normalized,
                COUNT(*) as app_count,
                MAX(employer_phone) as phone,
                MAX(employer_address) as address,
                MAX(employer_city) as city,
                MAX(employer_state) as state,
                MAX(employer_zip) as zip,
                MAX(contact_name) as contact_name,
                MAX(contact_email) as contact_email,
                MAX(job_url) as job_url,
                MAX(ats_type) as ats_type
            FROM applications
            WHERE company IS NOT NULL AND TRIM(company) != ''
            GROUP BY LOWER(TRIM(company))
        """)

        companies_data = cursor.fetchall()

        created = 0
        for row in companies_data:
            # Detect ATS type from job URL if not already set
            ats = row['ats_type'] or detect_ats_type(row['job_url'])

            cursor.execute("""
                INSERT OR IGNORE INTO companies (
                    name, name_normalized, careers_url, ats_type,
                    employer_phone, employer_address, employer_city,
                    employer_state, employer_zip, contact_name, contact_email
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                row['company'],
                row['normalized'],
                row['job_url'],  # Use job_url as initial careers_url
                ats,
                row['phone'],
                row['address'],
                row['city'],
                row['state'],
                row['zip'],
                row['contact_name'],
                row['contact_email'],
            ))

            if cursor.rowcount > 0:
                created += 1

        conn.commit()

        # Link applications to companies
        cursor.execute("""
            UPDATE applications
            SET company_id = (
                SELECT c.id FROM companies c
                WHERE c.name_normalized = LOWER(TRIM(applications.company))
            )
            WHERE company_id IS NULL
        """)
        linked = cursor.rowcount
        conn.commit()

        return {'companies_created': created, 'applications_linked': linked}


def link_geo_companies() -> int:
    """
    Link companies to geo_companies where names match.
    Returns count of companies linked.
    """
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE companies
            SET geo_company_id = (
                SELECT gc.id FROM geo_companies gc
                WHERE LOWER(TRIM(gc.name)) = companies.name_normalized
                LIMIT 1
            ),
            website = COALESCE(companies.website, (
                SELECT gc.website FROM geo_companies gc
                WHERE LOWER(TRIM(gc.name)) = companies.name_normalized
                LIMIT 1
            )),
            careers_url = COALESCE(companies.careers_url, (
                SELECT gc.careers_url FROM geo_companies gc
                WHERE LOWER(TRIM(gc.name)) = companies.name_normalized
                LIMIT 1
            ))
            WHERE companies.geo_company_id IS NULL
              AND EXISTS (
                  SELECT 1 FROM geo_companies gc
                  WHERE LOWER(TRIM(gc.name)) = companies.name_normalized
              )
        """)

        linked = cursor.rowcount
        conn.commit()

        return linked


# =============================================================================
# Investor Board Functions
# =============================================================================


def get_investor_boards(active_only: bool = True) -> list[dict[str, Any]]:
    """List investor boards, optionally filtered to active only."""
    with get_connection() as conn:
        cursor = conn.cursor()
        if active_only:
            cursor.execute("""
                SELECT *, (SELECT COUNT(*) FROM investor_board_jobs
                           WHERE investor_board_id = investor_boards.id AND is_active = 1
                          ) as active_job_count
                FROM investor_boards WHERE is_active = 1
                ORDER BY priority DESC, name
            """)
        else:
            cursor.execute("""
                SELECT *, (SELECT COUNT(*) FROM investor_board_jobs
                           WHERE investor_board_id = investor_boards.id AND is_active = 1
                          ) as active_job_count
                FROM investor_boards
                ORDER BY priority DESC, name
            """)
        return [dict(row) for row in cursor.fetchall()]


def get_investor_board(board_id: int) -> Optional[dict[str, Any]]:
    """Get a single investor board by ID."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM investor_boards WHERE id = ?", (board_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_investor_board_by_name(name: str) -> Optional[dict[str, Any]]:
    """Find investor board by name (case-insensitive)."""
    normalized = name.lower().strip()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM investor_boards WHERE name_normalized = ?",
            (normalized,)
        )
        row = cursor.fetchone()
        if row:
            return dict(row)
        # Fuzzy: try LIKE match
        cursor.execute(
            "SELECT * FROM investor_boards WHERE name_normalized LIKE ?",
            (f"%{normalized}%",)
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def create_investor_board(name: str, board_url: str = None, **kwargs) -> int:
    """Create a new investor board. Returns board ID."""
    normalized = name.lower().strip()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR IGNORE INTO investor_boards (
                name, name_normalized, short_name, board_url, ats_type,
                board_type, investor_type, has_talent_network,
                talent_network_url, talent_network_notes,
                portfolio_focus, geo_focus, is_active, priority, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            name, normalized,
            kwargs.get('short_name'),
            board_url,
            kwargs.get('ats_type'),
            kwargs.get('board_type', 'vc'),
            kwargs.get('investor_type'),
            kwargs.get('has_talent_network', False),
            kwargs.get('talent_network_url'),
            kwargs.get('talent_network_notes'),
            kwargs.get('portfolio_focus'),
            kwargs.get('geo_focus'),
            kwargs.get('is_active', True),
            kwargs.get('priority', 0),
            kwargs.get('notes'),
        ))
        conn.commit()

        if cursor.rowcount == 0:
            # Already exists — return existing ID
            cursor.execute(
                "SELECT id FROM investor_boards WHERE name_normalized = ?",
                (normalized,)
            )
            return cursor.fetchone()["id"]
        return cursor.lastrowid


def update_investor_board(board_id: int, **kwargs) -> bool:
    """Update investor board fields. Returns True if updated."""
    allowed = {
        'name', 'short_name', 'board_url', 'ats_type', 'board_type',
        'investor_type', 'has_talent_network', 'talent_network_url',
        'talent_network_notes', 'portfolio_focus', 'geo_focus',
        'is_active', 'priority', 'notes',
    }
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return False

    if 'name' in updates:
        updates['name_normalized'] = updates['name'].lower().strip()

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [board_id]

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"UPDATE investor_boards SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            values
        )
        conn.commit()
        return cursor.rowcount > 0


def get_investor_boards_due_for_check(hours: int = 24) -> list[dict[str, Any]]:
    """Get active boards not checked in the last N hours."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM investor_boards
            WHERE is_active = 1
              AND board_url IS NOT NULL
              AND (last_searched_at IS NULL
                   OR last_searched_at < datetime('now', ? || ' hours'))
            ORDER BY priority DESC, name
        """, (f"-{hours}",))
        return [dict(row) for row in cursor.fetchall()]


def increment_investor_board_search(board_id: int) -> None:
    """Bump search timestamp and count for a board."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE investor_boards
            SET times_searched = times_searched + 1,
                last_searched_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (board_id,))
        conn.commit()


def record_investor_board_job(board_id: int, url: str, title: str = None,
                              company_name: str = None, location: str = None,
                              salary: str = None,
                              company_id: int = None) -> tuple[int, bool]:
    """Record a job from an investor board. Returns (job_id, is_new).
    Uses INSERT OR IGNORE + UPDATE for upsert behavior."""
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            INSERT OR IGNORE INTO investor_board_jobs
                (investor_board_id, url, title, company_name, location, salary, company_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (board_id, url, title, company_name, location, salary, company_id))

        is_new = cursor.rowcount > 0

        if not is_new:
            cursor.execute("""
                UPDATE investor_board_jobs
                SET last_seen_at = CURRENT_TIMESTAMP,
                    is_active = 1,
                    title = COALESCE(?, title),
                    company_name = COALESCE(?, company_name),
                    location = COALESCE(?, location),
                    salary = COALESCE(?, salary),
                    company_id = COALESCE(?, company_id)
                WHERE investor_board_id = ? AND url = ?
            """, (title, company_name, location, salary, company_id, board_id, url))

        conn.commit()

        cursor.execute(
            "SELECT id FROM investor_board_jobs WHERE investor_board_id = ? AND url = ?",
            (board_id, url)
        )
        job_id = cursor.fetchone()["id"]

        # Update board job count
        cursor.execute("""
            UPDATE investor_boards
            SET job_count = (SELECT COUNT(*) FROM investor_board_jobs
                             WHERE investor_board_id = ? AND is_active = 1)
            WHERE id = ?
        """, (board_id, board_id))
        conn.commit()

        return (job_id, is_new)


def get_known_investor_board_job_urls(board_id: int) -> set[str]:
    """Get set of all known job URLs for a board (active and inactive)."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT url FROM investor_board_jobs WHERE investor_board_id = ?",
            (board_id,)
        )
        return {row["url"] for row in cursor.fetchall()}


def mark_stale_investor_board_jobs(board_id: int, active_urls: set[str]) -> int:
    """Mark jobs NOT in active_urls as inactive. Returns count marked stale."""
    with get_connection() as conn:
        cursor = conn.cursor()

        if not active_urls:
            cursor.execute("""
                UPDATE investor_board_jobs SET is_active = 0
                WHERE investor_board_id = ? AND is_active = 1
            """, (board_id,))
        else:
            placeholders = ",".join("?" for _ in active_urls)
            cursor.execute(f"""
                UPDATE investor_board_jobs SET is_active = 0
                WHERE investor_board_id = ? AND is_active = 1 AND url NOT IN ({placeholders})
            """, (board_id, *active_urls))

        stale_count = cursor.rowcount
        conn.commit()

        # Update board job count
        cursor.execute("""
            UPDATE investor_boards
            SET job_count = (SELECT COUNT(*) FROM investor_board_jobs
                             WHERE investor_board_id = ? AND is_active = 1)
            WHERE id = ?
        """, (board_id, board_id))
        conn.commit()

        return stale_count


def get_investor_board_jobs(board_id: int, active_only: bool = True) -> list[dict[str, Any]]:
    """Get jobs for an investor board."""
    with get_connection() as conn:
        cursor = conn.cursor()
        if active_only:
            cursor.execute("""
                SELECT * FROM investor_board_jobs
                WHERE investor_board_id = ? AND is_active = 1
                ORDER BY first_seen_at DESC
            """, (board_id,))
        else:
            cursor.execute("""
                SELECT * FROM investor_board_jobs
                WHERE investor_board_id = ?
                ORDER BY first_seen_at DESC
            """, (board_id,))
        return [dict(row) for row in cursor.fetchall()]


# =============================================================================
# Monitor Runs
# =============================================================================

def create_monitor_run(run_type: str = "full") -> int:
    """Create a new monitor run record. Returns the run ID."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO monitor_runs (run_type) VALUES (?)",
            (run_type,),
        )
        conn.commit()
        return cursor.lastrowid


def complete_monitor_run(
    run_id: int,
    companies_checked: int = 0,
    boards_checked: int = 0,
    new_listings_found: int = 0,
    notification_sent: bool = False,
    summary: dict | None = None,
    error_log: list | None = None,
) -> None:
    """Mark a monitor run as completed with results."""
    with get_connection() as conn:
        conn.execute(
            """UPDATE monitor_runs SET
                completed_at = CURRENT_TIMESTAMP,
                companies_checked = ?,
                boards_checked = ?,
                new_listings_found = ?,
                notification_sent = ?,
                summary = ?,
                error_log = ?
            WHERE id = ?""",
            (
                companies_checked,
                boards_checked,
                new_listings_found,
                notification_sent,
                json.dumps(summary) if summary else None,
                json.dumps(error_log) if error_log else None,
                run_id,
            ),
        )
        conn.commit()


def get_latest_monitor_run() -> Optional[dict[str, Any]]:
    """Get the most recent monitor run."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM monitor_runs ORDER BY started_at DESC LIMIT 1"
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def get_monitor_runs(limit: int = 10) -> list[dict[str, Any]]:
    """Get recent monitor runs."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM monitor_runs ORDER BY started_at DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]


def get_monitor_analytics(days: int = 30) -> dict[str, Any]:
    """Get monitor run analytics for the last N days.

    Returns dict with:
        total_runs, completed_runs, avg_new_listings, total_new_listings,
        avg_duration_seconds, company_yield (top companies by new listings),
        failure_rate, runs (list of run summaries)
    """
    with get_connection() as conn:
        cursor = conn.cursor()

        # Get runs in the date range
        cursor.execute(
            """SELECT * FROM monitor_runs
            WHERE started_at >= datetime('now', ?)
            ORDER BY started_at DESC""",
            (f"-{days} days",),
        )
        runs = [dict(row) for row in cursor.fetchall()]

        total_runs = len(runs)
        completed_runs = sum(1 for r in runs if r.get("completed_at"))
        total_new = sum(r.get("new_listings_found", 0) for r in runs)
        avg_new = total_new / total_runs if total_runs > 0 else 0

        # Parse summary JSON for enriched stats
        durations = []
        prospects_created = 0
        resumes_generated = 0
        scrape_failures = 0
        scoring_failures = 0
        resume_failures = 0
        email_syncs = 0

        for r in runs:
            summary_str = r.get("summary")
            if not summary_str:
                continue
            try:
                summary = json.loads(summary_str)
            except (json.JSONDecodeError, TypeError):
                continue

            if "duration_seconds" in summary:
                durations.append(summary["duration_seconds"])
            prospects_created += summary.get("prospects_created", 0)
            resumes_generated += summary.get("resumes_generated", 0)
            scrape_failures += summary.get("scrape_failures", 0)
            scoring_failures += summary.get("scoring_failures", 0)
            resume_failures += summary.get("resume_failures", 0)
            if summary.get("email_sync"):
                email_syncs += 1

        avg_duration = sum(durations) / len(durations) if durations else None

        # Company yield: which companies produced the most new listings
        cursor.execute(
            """SELECT c.name, COUNT(*) as new_count
            FROM job_listings jl
            JOIN companies c ON c.id = jl.company_id
            WHERE jl.first_seen_at >= datetime('now', ?)
            GROUP BY c.id
            ORDER BY new_count DESC
            LIMIT 10""",
            (f"-{days} days",),
        )
        company_yield = [dict(row) for row in cursor.fetchall()]

        return {
            "days": days,
            "total_runs": total_runs,
            "completed_runs": completed_runs,
            "total_new_listings": total_new,
            "avg_new_listings": round(avg_new, 1),
            "avg_duration_seconds": round(avg_duration, 1) if avg_duration else None,
            "prospects_created": prospects_created,
            "resumes_generated": resumes_generated,
            "scrape_failures": scrape_failures,
            "scoring_failures": scoring_failures,
            "resume_failures": resume_failures,
            "email_syncs": email_syncs,
            "company_yield": company_yield,
            "runs": runs,
        }



# Sender domains that are noise — not actual application correspondence
_NOISE_SENDER_PATTERNS = (
    "%ziprecruiter.com%",
    "%substack.com%",
    "%userinterviews.com%",
    "%updates@m.discord.com%",
    "%jointheflyover%",
    "%notifications@mail.pos%",
    "%invoice+statements@%",
    "%alerts@ziprecruiter%",
    "%@linkedin.com%",
    "%@builtin.com%",
    "%@maven.com%",
)


def get_email_sync_feed(days: int = 30) -> list[dict[str, Any]]:
    """Get email sync activity feed: emails discovered, grouped by day.

    Filters out noise (newsletters, alerts, marketing) by sender domain.

    Returns list of dicts with: id, application_id, company, position,
    email_type, resolution_type, email_id, sender, subject, received_at,
    created_at (when sync discovered it).
    """
    with get_connection() as conn:
        cursor = conn.cursor()

        noise_clause = " AND ".join(
            f"ae.sender NOT LIKE ?" for _ in _NOISE_SENDER_PATTERNS
        )

        cursor.execute(
            f"""SELECT ae.id, ae.application_id, ae.email_type, ae.resolution_type,
                      ae.email_id, ae.sender, ae.subject, ae.received_at, ae.created_at,
                      a.company, a.position, a.status as app_status, a.location,
                      a.job_url, a.fit_score, a.applied_at
               FROM application_emails ae
               JOIN applications a ON a.id = ae.application_id
               WHERE ae.created_at >= datetime('now', ?)
                 AND {noise_clause}
               ORDER BY ae.created_at DESC""",
            (f"-{days} days", *_NOISE_SENDER_PATTERNS),
        )
        return [dict(row) for row in cursor.fetchall()]


def get_company_scrape_stats(company_id: int) -> dict[str, Any]:
    """Get per-company scrape performance stats.

    Returns dict with:
        company_name, total_listings, active_listings, stale_listings,
        total_scrapes, last_scraped, avg_new_per_scrape, failure_indicators
    """
    with get_connection() as conn:
        cursor = conn.cursor()

        # Company info
        cursor.execute("SELECT * FROM companies WHERE id = ?", (company_id,))
        company = cursor.fetchone()
        if not company:
            return {"error": f"Company {company_id} not found"}
        company = dict(company)

        # Listing stats
        cursor.execute(
            """SELECT
                COUNT(*) as total,
                SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) as active,
                SUM(CASE WHEN is_active = 0 THEN 1 ELSE 0 END) as stale
            FROM job_listings WHERE company_id = ?""",
            (company_id,),
        )
        listing_stats = dict(cursor.fetchone())

        # Scrape history from search_count
        search_count = company.get("search_count", 0)
        last_searched = company.get("last_searched_at")

        # New listings over time
        cursor.execute(
            """SELECT COUNT(*) as new_30d FROM job_listings
            WHERE company_id = ? AND first_seen_at >= datetime('now', '-30 days')""",
            (company_id,),
        )
        new_30d = cursor.fetchone()["new_30d"]

        avg_new = new_30d / search_count if search_count > 0 else 0

        # Check for potential issues
        failure_indicators = []
        if search_count > 5 and new_30d == 0:
            failure_indicators.append("No new listings in 30 days — consider removing or checking URL")
        if listing_stats["active"] == 0 and listing_stats["total"] > 0:
            failure_indicators.append("All listings stale — career page may have changed")

        return {
            "company_name": company.get("name"),
            "careers_url": company.get("careers_url"),
            "total_listings": listing_stats["total"],
            "active_listings": listing_stats["active"],
            "stale_listings": listing_stats["stale"],
            "total_scrapes": search_count,
            "last_scraped": last_searched,
            "new_last_30d": new_30d,
            "avg_new_per_scrape": round(avg_new, 2),
            "failure_indicators": failure_indicators,
        }
