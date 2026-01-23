"""Gmail integration for job application verification.

This module provides:
- GmailClient: Wrapper for Gmail API with authentication
- verify_confirmations(): Check for application confirmation emails
- search_updates(): Find interview/rejection/update emails
"""

import base64
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from jj.config import JJ_HOME


# Gmail API imports (with graceful fallback)
try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    GMAIL_AVAILABLE = True
except ImportError:
    GMAIL_AVAILABLE = False


# OAuth scopes for Gmail read-only access
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

# Paths for Gmail credentials
CREDENTIALS_PATH = JJ_HOME / "credentials.json"
TOKEN_PATH = JJ_HOME / "token.json"

# Path to email domains config
EMAIL_DOMAINS_PATH = Path(__file__).parent / "email_domains.yaml"


@dataclass
class EmailMatch:
    """A matched email for an application."""
    message_id: str
    subject: str
    sender: str
    date: datetime
    snippet: str
    gmail_link: str
    match_type: str  # 'confirmation', 'update', 'rejection', 'interview'


@dataclass
class VerificationResult:
    """Result of verifying an application's confirmation email."""
    company: str
    position: Optional[str]
    applied_at: Optional[datetime]
    confirmed: bool
    email: Optional[EmailMatch] = None
    search_queries_used: list[str] = field(default_factory=list)


@dataclass
class UpdateResult:
    """An update found for an application."""
    company: str
    position: Optional[str]
    email: EmailMatch
    update_type: str  # 'interview', 'rejection', 'next_steps', 'assessment', 'unknown'
    action_required: bool = False


def load_email_domains() -> dict:
    """Load email domain mappings from YAML config."""
    if EMAIL_DOMAINS_PATH.exists():
        with open(EMAIL_DOMAINS_PATH) as f:
            return yaml.safe_load(f) or {}
    return {}


def save_company_domain(company: str, domain: str) -> None:
    """Add or update a company's email domain mapping."""
    config = load_email_domains()
    if "companies" not in config:
        config["companies"] = {}
    config["companies"][company] = domain

    with open(EMAIL_DOMAINS_PATH, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)


def get_ats_domains() -> list[str]:
    """Get all known ATS email domains."""
    config = load_email_domains()
    domains = []
    for ats_emails in config.get("ats_patterns", {}).values():
        domains.extend(ats_emails)
    return domains


def get_company_domain(company: str) -> Optional[str]:
    """Get known email domain for a company."""
    config = load_email_domains()
    return config.get("companies", {}).get(company)


class GmailClient:
    """Client for Gmail API operations."""

    def __init__(self):
        """Initialize the Gmail client."""
        if not GMAIL_AVAILABLE:
            raise ImportError(
                "Gmail dependencies not installed. Install with:\n"
                "pip install google-api-python-client google-auth-oauthlib"
            )

        self.service = None
        self._config = load_email_domains()

    def authenticate(self) -> bool:
        """Authenticate with Gmail API. Returns True if successful."""
        creds = None

        # Load existing token
        if TOKEN_PATH.exists():
            creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

        # Refresh or get new credentials
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not CREDENTIALS_PATH.exists():
                    raise FileNotFoundError(
                        f"Gmail credentials not found at {CREDENTIALS_PATH}.\n"
                        f"Copy credentials.json from your Gmail API project to {JJ_HOME}"
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(CREDENTIALS_PATH), SCOPES
                )
                creds = flow.run_local_server(port=0)

            # Save refreshed/new token
            with open(TOKEN_PATH, "w") as f:
                f.write(creds.to_json())

        self.service = build("gmail", "v1", credentials=creds)
        return True

    def search(self, query: str, max_results: int = 50) -> list[dict]:
        """Search for emails matching query. Returns list of message metadata."""
        if not self.service:
            self.authenticate()

        results = self.service.users().messages().list(
            userId="me",
            q=query,
            maxResults=max_results
        ).execute()

        messages = results.get("messages", [])
        return messages

    def get_message(self, message_id: str) -> dict:
        """Get full message details by ID."""
        if not self.service:
            self.authenticate()

        return self.service.users().messages().get(
            userId="me",
            id=message_id,
            format="metadata",
            metadataHeaders=["From", "Subject", "Date"]
        ).execute()

    def _parse_message(self, msg: dict) -> EmailMatch:
        """Parse Gmail message into EmailMatch."""
        headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}

        # Parse date
        date_str = headers.get("Date", "")
        try:
            # Handle various date formats
            for fmt in [
                "%a, %d %b %Y %H:%M:%S %z",
                "%d %b %Y %H:%M:%S %z",
                "%a, %d %b %Y %H:%M:%S %Z",
            ]:
                try:
                    date = datetime.strptime(date_str.split(" (")[0].strip(), fmt)
                    break
                except ValueError:
                    continue
            else:
                date = datetime.now()
        except Exception:
            date = datetime.now()

        return EmailMatch(
            message_id=msg["id"],
            subject=headers.get("Subject", ""),
            sender=headers.get("From", ""),
            date=date,
            snippet=msg.get("snippet", ""),
            gmail_link=f"https://mail.google.com/mail/u/0/#inbox/{msg['id']}",
            match_type="unknown"
        )

    def search_for_company(
        self,
        company: str,
        after_date: Optional[datetime] = None,
        search_type: str = "confirmation"
    ) -> list[EmailMatch]:
        """Search for emails related to a company.

        Args:
            company: Company name to search for
            after_date: Only find emails after this date
            search_type: 'confirmation' or 'update'

        Returns:
            List of matching emails
        """
        queries = self._build_company_queries(company, after_date, search_type)

        seen_ids = set()
        results = []

        for query in queries:
            messages = self.search(query, max_results=10)

            for msg_summary in messages:
                if msg_summary["id"] in seen_ids:
                    continue
                seen_ids.add(msg_summary["id"])

                msg = self.get_message(msg_summary["id"])
                email_match = self._parse_message(msg)
                email_match.match_type = self._classify_email(email_match, search_type)
                results.append(email_match)

        return results

    def _build_company_queries(
        self,
        company: str,
        after_date: Optional[datetime],
        search_type: str
    ) -> list[str]:
        """Build Gmail search queries for a company."""
        queries = []
        date_filter = ""

        if after_date:
            date_filter = f" after:{after_date.strftime('%Y/%m/%d')}"

        # Clean company name for search
        clean_company = company.replace('"', "").strip()

        if search_type == "confirmation":
            # Search 1: Company name in subject with confirmation keywords
            queries.append(
                f'subject:("{clean_company}") '
                f'(thank applying OR application received OR thanks applying){date_filter}'
            )

            # Search 2: From company domain if known
            domain = get_company_domain(company)
            if domain:
                queries.append(
                    f'from:(@{domain}) '
                    f'(thank applying OR application received){date_filter}'
                )

            # Search 3: ATS platforms with company in subject
            ats_from = " OR ".join([
                "ashbyhq", "greenhouse", "lever", "icims", "rippling", "workday"
            ])
            queries.append(
                f'from:({ats_from}) subject:("{clean_company}"){date_filter}'
            )

        elif search_type == "update":
            # Keywords for updates - single words work better with Gmail OR
            update_keywords = " OR ".join([
                "interview", "schedule", "assessment",
                "unfortunately", "regret", "decision",
                "offer", "update", "follow", "status"
            ])

            # Search 1: Company in subject with update keywords
            queries.append(
                f'subject:("{clean_company}") ({update_keywords}){date_filter}'
            )

            # Search 2: From company domain (more reliable)
            domain = get_company_domain(company)
            if domain:
                queries.append(
                    f'from:(@{domain}){date_filter}'
                )

            # Search 3: ATS with company name anywhere
            ats_from = " OR ".join([
                "ashbyhq", "greenhouse", "lever", "icims", "rippling"
            ])
            queries.append(
                f'from:({ats_from}) "{clean_company}" ({update_keywords}){date_filter}'
            )

        return queries

    def _classify_email(self, email: EmailMatch, search_type: str) -> str:
        """Classify an email based on its content."""
        subject_lower = email.subject.lower()
        snippet_lower = email.snippet.lower()
        combined = subject_lower + " " + snippet_lower

        # Check for rejection signals
        rejection_signals = [
            "unfortunately", "not moving forward", "other candidates",
            "decided not to", "not be moving", "regret", "will not"
        ]
        if any(sig in combined for sig in rejection_signals):
            return "rejection"

        # Check for interview signals
        interview_signals = [
            "interview", "schedule", "calendar", "phone screen",
            "video call", "meet with", "speak with"
        ]
        if any(sig in combined for sig in interview_signals):
            return "interview"

        # Check for next steps / assessment
        next_steps_signals = [
            "next step", "assessment", "take-home", "coding challenge",
            "complete", "action required"
        ]
        if any(sig in combined for sig in next_steps_signals):
            return "next_steps"

        # Check for confirmation
        confirmation_signals = [
            "thank you for applying", "application received",
            "we received your", "thanks for applying", "application submitted"
        ]
        if any(sig in combined for sig in confirmation_signals):
            return "confirmation"

        return search_type  # Default to the search type


def verify_confirmations(
    applications: list[dict],
    verbose: bool = False,
    save_to_db: bool = True
) -> list[VerificationResult]:
    """Verify confirmation emails for a list of applications.

    Args:
        applications: List of application dicts with 'company', 'position', 'applied_at'
        verbose: Print progress if True
        save_to_db: Save results to the database

    Returns:
        List of VerificationResult for each application
    """
    client = GmailClient()
    client.authenticate()

    # Import db functions if saving
    if save_to_db:
        from jj.db import update_application_email_confirmation

    results = []

    for app in applications:
        company = app.get("company", "")
        position = app.get("position")
        applied_at = app.get("applied_at")
        app_id = app.get("id")

        # Parse applied_at if string
        if isinstance(applied_at, str) and applied_at:
            try:
                applied_at = datetime.fromisoformat(applied_at.replace("Z", "+00:00"))
            except ValueError:
                applied_at = None

        if verbose:
            print(f"Checking {company}...")

        # Search for confirmation emails
        emails = client.search_for_company(
            company,
            after_date=applied_at,
            search_type="confirmation"
        )

        # Filter to actual confirmations
        confirmation_emails = [
            e for e in emails
            if e.match_type == "confirmation"
        ]

        result = VerificationResult(
            company=company,
            position=position,
            applied_at=applied_at,
            confirmed=len(confirmation_emails) > 0,
            email=confirmation_emails[0] if confirmation_emails else None
        )
        results.append(result)

        # Save to database
        if save_to_db and app_id:
            if confirmation_emails:
                email = confirmation_emails[0]
                update_application_email_confirmation(
                    app_id=app_id,
                    confirmed=True,
                    confirmed_at=email.date.isoformat(),
                    email_id=email.message_id,
                )
            else:
                update_application_email_confirmation(
                    app_id=app_id,
                    confirmed=False,
                )

        # Learn domain if we found a match
        if confirmation_emails:
            email = confirmation_emails[0]
            # Extract domain from sender
            match = re.search(r"@([a-zA-Z0-9.-]+)", email.sender)
            if match:
                sender_domain = match.group(1).lower()
                # Don't save ATS domains as company domains
                ats_domains = get_ats_domains()
                if not any(ats in sender_domain for ats in ["ashby", "greenhouse", "lever", "icims", "rippling"]):
                    # Check if we should save this domain
                    existing = get_company_domain(company)
                    if not existing:
                        save_company_domain(company, sender_domain)

    return results


def search_updates(
    applications: list[dict],
    since: Optional[datetime] = None,
    verbose: bool = False,
    save_to_db: bool = True
) -> list[UpdateResult]:
    """Search for update emails for applications.

    Args:
        applications: List of application dicts
        since: Only find emails after this date (default: 7 days ago)
        verbose: Print progress if True
        save_to_db: Save results to the database

    Returns:
        List of UpdateResult for emails found
    """
    from datetime import timedelta

    if since is None:
        since = datetime.now() - timedelta(days=7)

    client = GmailClient()
    client.authenticate()

    # Import db functions if saving
    if save_to_db:
        from jj.db import update_application_latest_update

    results = []
    seen_message_ids = set()
    # Track latest update per application
    app_latest_updates: dict[int, UpdateResult] = {}

    for app in applications:
        company = app.get("company", "")
        position = app.get("position")
        app_id = app.get("id")

        if verbose:
            print(f"Searching updates for {company}...")

        emails = client.search_for_company(
            company,
            after_date=since,
            search_type="update"
        )

        for email in emails:
            # Skip duplicates
            if email.message_id in seen_message_ids:
                continue
            seen_message_ids.add(email.message_id)

            # Skip confirmation emails in update search
            if email.match_type == "confirmation":
                continue

            # Determine if action is required
            action_required = email.match_type in ["interview", "next_steps"]

            result = UpdateResult(
                company=company,
                position=position,
                email=email,
                update_type=email.match_type,
                action_required=action_required
            )
            results.append(result)

            # Track latest update for this application
            if app_id:
                existing = app_latest_updates.get(app_id)
                if not existing or email.date > existing.email.date:
                    app_latest_updates[app_id] = result

    # Save latest updates to database
    if save_to_db:
        for app_id, update in app_latest_updates.items():
            update_application_latest_update(
                app_id=app_id,
                update_type=update.update_type,
                update_at=update.email.date.isoformat(),
                subject=update.email.subject,
                email_id=update.email.message_id,
            )

    return results


def search_company_emails(company: str, max_results: int = 10) -> list[EmailMatch]:
    """Search for all emails related to a company. Useful for testing."""
    client = GmailClient()
    client.authenticate()

    # Simple search for company name
    clean_company = company.replace('"', "").strip()
    query = f'"{clean_company}"'

    messages = client.search(query, max_results=max_results)

    results = []
    for msg_summary in messages:
        msg = client.get_message(msg_summary["id"])
        email_match = client._parse_message(msg)
        email_match.match_type = client._classify_email(email_match, "update")
        results.append(email_match)

    return results
