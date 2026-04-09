"""Configuration management for Job Journal."""

from pathlib import Path
from typing import Any

import yaml

# Default paths
JJ_HOME = Path.home() / ".job-journal"
DB_PATH = JJ_HOME / "journal.db"
CORPUS_PATH = JJ_HOME / "corpus.md"
PROFILE_PATH = JJ_HOME / "profile.yaml"
CONFIG_PATH = JJ_HOME / "config.yaml"

# Default profile template
DEFAULT_PROFILE: dict[str, Any] = {
    "name": {
        "first": "",
        "last": "",
        "preferred": "",
    },
    "contact": {
        "email": "",
        "phone": "",
        "location": "",
    },
    "links": {
        "linkedin": "",
        "github": "",
        "portfolio": "",
    },
    "authorization": {
        "status": "",
        "requires_sponsorship": False,
    },
    "experience": {
        "years": 0,
        "current_title": "",
        "current_company": "",
    },
    "education": [],
    "defaults": {
        "pronouns": "",
        "hear_about_us": "LinkedIn",
        "willing_to_relocate": True,
        "remote_preference": "flexible",
    },
    "interests": "",
    "voice": {
        "tone": "direct",
        "patterns": [],
        "avoids": [],
    },
    "summaries": {
        "growth": "",
        "ai-agentic": "",
        "health-tech": "",
        "general": "",
    },
}

# Default config template
DEFAULT_CONFIG: dict[str, Any] = {
    "output": {
        "folder": str(Path.home() / "Documents" / "Resumes"),
        "naming_pattern": "{name} - {title} - {company} - Resume",
        "format": "docx",
    },
    "resume": {
        "default_variant": "general",
        "template": "templates/reference.docx",
    },
    "variants": {
        "growth": ["growth", "plg", "experimentation", "activation", "retention", "funnel"],
        "ai-agentic": ["ai", "agentic", "llm", "orchestration", "automation", "agent"],
        "health-tech": ["health", "healthcare", "ehr", "hipaa", "clinical", "patient"],
        "consumer": ["b2c", "consumer", "dtc", "marketplace", "e-commerce"],
        "general": ["product manager", "roadmap", "strategy", "cross-functional"],
    },
    "google_docs": {
        "template_id": "",
        "pdf_output_dir": str(Path.home() / "Documents" / "Resumes"),
        "auto_open": True,
        "keep_google_doc": True,
    },
    "monitor": {
        "schedule_hours": [6, 12],
        "check_interval_hours": 12,
        "notify_threshold": 50,
        "slack_webhook_url": "",
        # Socket Mode bot for interactive [Score] buttons
        "slack_bot_token": "",          # xoxb-... Bot User OAuth Token
        "slack_app_token": "",          # xapp-... App-Level Token (connections:write)
        "slack_default_channel": "",    # C0123... channel where notifications post
        "slack_authorized_users": [],   # Slack user IDs allowed to click buttons; empty = no restriction
    },
}


def ensure_jj_home() -> None:
    """Create Job Journal home directory structure."""
    JJ_HOME.mkdir(exist_ok=True)
    (JJ_HOME / "resumes").mkdir(exist_ok=True)
    (JJ_HOME / "exports").mkdir(exist_ok=True)
    (JJ_HOME / "logs").mkdir(exist_ok=True)


def load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML file."""
    if not path.exists():
        return {}
    with open(path) as f:
        return yaml.safe_load(f) or {}


def save_yaml(path: Path, data: dict[str, Any]) -> None:
    """Save data to a YAML file."""
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def load_profile() -> dict[str, Any]:
    """Load the user profile."""
    return load_yaml(PROFILE_PATH) or DEFAULT_PROFILE.copy()


def save_profile(profile: dict[str, Any]) -> None:
    """Save the user profile."""
    save_yaml(PROFILE_PATH, profile)


def load_config() -> dict[str, Any]:
    """Load the application config."""
    return load_yaml(CONFIG_PATH) or DEFAULT_CONFIG.copy()


def save_config(config: dict[str, Any]) -> None:
    """Save the application config."""
    save_yaml(CONFIG_PATH, config)


def get_full_name() -> str:
    """Get the user's full name from profile."""
    profile = load_profile()
    first = profile.get("name", {}).get("first", "")
    last = profile.get("name", {}).get("last", "")
    return f"{first} {last}".strip()
