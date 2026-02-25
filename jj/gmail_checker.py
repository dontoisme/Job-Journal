"""Gmail integration for job application verification.

This module provides:
- GmailClient: Wrapper for Gmail API with authentication
- verify_confirmations(): Check for application confirmation emails
- search_updates(): Find interview/rejection/update emails
"""

import base64
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
TOKEN_PATH = JJ_HOME / "gmail_token.json"

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


@dataclass
class PairingResult:
    """Result of pairing an email to an application."""
    application_id: int
    company: str
    email: EmailMatch
    pair_type: str  # 'confirmation' or 'resolution'
    resolution_type: Optional[str] = None  # 'rejection', 'screening', 'interview', 'offer'
    saved: bool = False


# Resolution signal patterns for email classification
RESOLUTION_SIGNALS = {
    'rejection': [
        "thank you for your interest",
        "unfortunately", "not moving forward",
        "other candidates", "position has been filled",
        "wish you the best", "will not be pursuing",
        "decided not to proceed", "gone with another candidate",
        "regret to inform", "not a fit", "not the right fit",
        "pursued other candidates", "best of luck",
    ],
    'screening': [
        "would like to schedule", "interested in speaking",
        "learn more about your experience", "phone call",
        "initial conversation", "recruiter",
        "quick chat", "15 minute", "30 minute",
        "brief call", "phone screen",
    ],
    'interview': [
        "interview", "meet with the team",
        "technical assessment", "take-home",
        "next round", "panel", "on-site",
        "video interview", "meet our team",
    ],
    'offer': [
        "offer", "compensation", "start date",
        "background check", "we'd like to extend",
        "pleased to offer", "congratulations",
    ]
}


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


def infer_company_domain(company: str) -> Optional[str]:
    """Infer likely email domain from company name.

    Examples:
        "PostHog" → "posthog.com"
        "Babylist" → "babylist.com"
        "Outdoorsy/Roamly" → "outdoorsy.com" (takes first part)
        "Memorial Sloan Kettering" → "mskcc.org" (needs manual mapping)
        "Acme Corp" → "acme.com"
    """
    # First check if we have it stored
    known = get_company_domain(company)
    if known:
        return known

    # Clean and normalize company name
    clean = company.lower().strip()

    # Split on common separators and use the first/primary name
    # e.g., "Outdoorsy/Roamly" → "Outdoorsy", "Company (DBA Name)" → "Company"
    for separator in ['/', '|', ' - ', ' (', ' — ']:
        if separator in clean:
            clean = clean.split(separator)[0].strip()

    # Remove common suffixes
    for suffix in [", inc.", ", inc", " inc.", " inc", ", llc", " llc",
                   ", corp.", " corp.", " corp", ", co.", " co.",
                   " corporation", " company", " technologies", " software"]:
        if clean.endswith(suffix):
            clean = clean[:-len(suffix)]

    # Remove special characters and spaces
    clean = re.sub(r'[^a-z0-9]', '', clean)

    if clean:
        return f"{clean}.com"
    return None


def get_company_search_names(company: str) -> list[str]:
    """Get list of company name variants for search.

    For "Outdoorsy/Roamly", returns ["Outdoorsy/Roamly", "Outdoorsy", "Roamly"]
    """
    names = [company]

    # Split on common separators
    for separator in ['/', '|', ' - ', ' — ']:
        if separator in company:
            parts = [p.strip() for p in company.split(separator)]
            names.extend(parts)

    # Handle parenthetical names like "Company (DBA)"
    if ' (' in company and ')' in company:
        main = company.split(' (')[0].strip()
        paren = company.split('(')[1].split(')')[0].strip()
        if main not in names:
            names.append(main)
        if paren not in names:
            names.append(paren)

    return names


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
                try:
                    creds.refresh(Request())
                except Exception:
                    # Token revoked or refresh failed — delete stale token, start fresh
                    if TOKEN_PATH.exists():
                        TOKEN_PATH.unlink()
                    creds = None
            if not creds or not creds.valid:
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

    def get_message_body(self, message_id: str) -> tuple[dict, str]:
        """Get message with full body text.

        Returns:
            Tuple of (headers dict, body text)
        """
        if not self.service:
            self.authenticate()

        message = self.service.users().messages().get(
            userId="me",
            id=message_id,
            format="full"
        ).execute()

        # Extract headers
        headers = {}
        for header in message.get("payload", {}).get("headers", []):
            headers[header["name"]] = header["value"]

        # Extract body
        payload = message.get("payload", {})
        body = self._extract_body(payload)

        return headers, body

    def _extract_body(self, payload: dict) -> str:
        """Extract text body from message payload."""
        parts = payload.get("parts", [])

        if parts:
            # Multipart message - look for text/plain first
            for part in parts:
                mime_type = part.get("mimeType", "")
                if mime_type == "text/plain":
                    data = part.get("body", {}).get("data", "")
                    if data:
                        return base64.urlsafe_b64decode(data).decode("utf-8")
                # Recursively check nested parts
                if part.get("parts"):
                    nested = self._extract_body(part)
                    if nested:
                        return nested
            # Fallback to text/html if no plain text
            for part in parts:
                if part.get("mimeType") == "text/html":
                    data = part.get("body", {}).get("data", "")
                    if data:
                        html = base64.urlsafe_b64decode(data).decode("utf-8")
                        # Basic HTML to text conversion
                        import re
                        text = re.sub(r'<br\s*/?>', '\n', html)
                        text = re.sub(r'<[^>]+>', '', text)
                        text = re.sub(r'&nbsp;', ' ', text)
                        text = re.sub(r'&amp;', '&', text)
                        text = re.sub(r'&lt;', '<', text)
                        text = re.sub(r'&gt;', '>', text)
                        return text.strip()
        else:
            # Simple message
            data = payload.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8")

        return ""

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
        """Build Gmail search queries for a company.

        PRIORITY ORDER (most reliable first):
        1. Sender domain (inferred or known) - catches personal recruiter emails
        2. ATS platforms with company name variants
        3. Subject line keywords (fallback)
        """
        queries = []
        date_filter = ""

        if after_date:
            date_filter = f" after:{after_date.strftime('%Y/%m/%d')}"

        # Get all company name variants for search
        # e.g., "Outdoorsy/Roamly" → ["Outdoorsy/Roamly", "Outdoorsy", "Roamly"]
        company_names = get_company_search_names(company)
        company_names[0].replace('"', "").strip()

        # Get domain - try known first, then infer
        domain = get_company_domain(company) or infer_company_domain(company)

        if search_type == "confirmation":
            # PRIORITY 1: From company domain (catches all company emails)
            if domain:
                queries.append(
                    f'from:(@{domain}){date_filter}'
                )

            # PRIORITY 2: ATS platforms with company name variants in subject
            ats_from = " OR ".join([
                "ashbyhq", "greenhouse", "lever", "icims", "rippling", "workday", "workable", "workablemail"
            ])
            # Search for each company name variant
            for name in company_names:
                clean_name = name.replace('"', "").strip()
                queries.append(
                    f'from:({ats_from}) subject:("{clean_name}"){date_filter}'
                )

            # PRIORITY 3: Company name in subject with confirmation keywords
            for name in company_names:
                clean_name = name.replace('"', "").strip()
                queries.append(
                    f'subject:("{clean_name}") '
                    f'(thank applying OR application received OR thanks applying){date_filter}'
                )

        elif search_type == "update":
            # PRIORITY 1: From company domain (catches personal recruiter emails!)
            # This is the key fix - search ALL emails from company domain
            if domain:
                queries.append(
                    f'from:(@{domain}){date_filter}'
                )

            # PRIORITY 2: ATS with company name variants anywhere
            ats_from = " OR ".join([
                "ashbyhq", "greenhouse", "lever", "icims", "rippling", "workable", "workablemail"
            ])
            for name in company_names:
                clean_name = name.replace('"', "").strip()
                queries.append(
                    f'from:({ats_from}) "{clean_name}"{date_filter}'
                )

            # PRIORITY 3: Company name variants in subject with update keywords (fallback)
            update_keywords = " OR ".join([
                "interview", "schedule", "assessment",
                "unfortunately", "regret", "decision",
                "offer", "update", "follow", "status",
                "application", "position", "role"
            ])
            for name in company_names:
                clean_name = name.replace('"', "").strip()
                queries.append(
                    f'subject:("{clean_name}") ({update_keywords}){date_filter}'
                )

        return queries

    def _classify_email(self, email: EmailMatch, search_type: str) -> str:
        """Classify an email based on its content."""
        subject_lower = email.subject.lower()
        snippet_lower = email.snippet.lower()
        combined = subject_lower + " " + snippet_lower

        # Check for confirmation FIRST — ATS platforms (Lever, Greenhouse) often
        # use "thank you for your interest" in confirmation emails alongside
        # "we received your application", which would otherwise match rejection.
        confirmation_signals = [
            "thank you for applying", "application received",
            "we received your", "thanks for applying", "application submitted",
            "we received your application", "will review your application",
            "delighted that you would consider",
        ]
        if any(sig in combined for sig in confirmation_signals):
            return "confirmation"

        # Check for rejection signals (including soft rejection language)
        rejection_signals = [
            "unfortunately", "not moving forward", "other candidates",
            "decided not to", "not be moving", "regret", "will not",
            # Soft rejection language
            "thank you for your interest",  # Common soft rejection
            "wish you the best", "best of luck in your",
            "pursued other candidates", "gone with another",
            "not a fit", "not the right fit",
            "position has been filled", "role has been filled",
        ]
        if any(sig in combined for sig in rejection_signals):
            return "rejection"

        # Check for interview signals
        interview_signals = [
            "interview", "schedule", "calendar", "phone screen",
            "video call", "meet with", "speak with", "chat with",
            "would like to discuss", "next round"
        ]
        if any(sig in combined for sig in interview_signals):
            return "interview"

        # Check for next steps / assessment
        next_steps_signals = [
            "next step", "assessment", "take-home", "coding challenge",
            "complete", "action required", "please submit", "please complete"
        ]
        if any(sig in combined for sig in next_steps_signals):
            return "next_steps"

        # Check for generic application update (catch-all for recruiter emails)
        update_signals = [
            "your application", "regarding your", "your recent application",
            "following up", "wanted to reach out"
        ]
        if any(sig in combined for sig in update_signals):
            return "update"

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
                get_ats_domains()
                if not any(ats in sender_domain for ats in ["ashby", "greenhouse", "lever", "icims", "rippling", "workable"]):
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


@dataclass
class EmailContent:
    """Full email content including body."""
    message_id: str
    subject: str
    sender: str
    date: str
    body: str
    gmail_link: str


def read_email(message_id: str) -> EmailContent:
    """Read full email content by message ID.

    Args:
        message_id: Gmail message ID (from EmailMatch or URL)

    Returns:
        EmailContent with full body text
    """
    client = GmailClient()
    client.authenticate()

    headers, body = client.get_message_body(message_id)

    return EmailContent(
        message_id=message_id,
        subject=headers.get("Subject", ""),
        sender=headers.get("From", ""),
        date=headers.get("Date", ""),
        body=body,
        gmail_link=f"https://mail.google.com/mail/u/0/#inbox/{message_id}"
    )


# Email Pairing Functions

def classify_resolution_type(email: EmailMatch) -> Optional[str]:
    """Classify the resolution type of an email.

    Returns one of: 'rejection', 'screening', 'interview', 'offer', or None
    """
    combined = (email.subject + " " + email.snippet).lower()

    # Check each resolution type in order of specificity
    # (offer is most specific, rejection is most common)
    for resolution_type in ['offer', 'interview', 'screening', 'rejection']:
        signals = RESOLUTION_SIGNALS.get(resolution_type, [])
        if any(sig in combined for sig in signals):
            return resolution_type

    return None


def classify_email_pair_type(
    email: EmailMatch,
    application: dict
) -> tuple[str, Optional[str]]:
    """Determine if email is confirmation or resolution for an application.

    Args:
        email: The email to classify
        application: Application dict with pairing info

    Returns:
        Tuple of (pair_type, resolution_type) where:
        - pair_type: 'confirmation', 'resolution', or 'unknown'
        - resolution_type: For resolutions - 'rejection', 'screening', 'interview', 'offer'
    """
    from jj.db import get_confirmation_email, get_resolution_email

    combined = (email.subject + " " + email.snippet).lower()
    app_id = application.get('id')

    # Check if this looks like a confirmation email
    confirmation_signals = [
        "thank you for applying", "application received",
        "we received your", "thanks for applying",
        "application submitted", "application has been received",
        "thank you for your application"
    ]
    is_confirmation_like = any(sig in combined for sig in confirmation_signals)

    # Check if application already has confirmation
    existing_confirmation = get_confirmation_email(app_id) if app_id else None
    existing_resolution = get_resolution_email(app_id) if app_id else None

    # If application has no confirmation yet and this looks like one
    if not existing_confirmation and is_confirmation_like:
        return ('confirmation', None)

    # If application has confirmation but no resolution, check for resolution
    if existing_confirmation and not existing_resolution:
        resolution_type = classify_resolution_type(email)
        if resolution_type:
            return ('resolution', resolution_type)

    # Even if no confirmation, a resolution email can arrive (some companies skip confirmation)
    resolution_type = classify_resolution_type(email)
    if resolution_type:
        return ('resolution', resolution_type)

    # Default to confirmation if this is the first email and looks like initial contact
    if not existing_confirmation:
        return ('confirmation', None)

    return ('unknown', None)


def match_email_to_application(
    email: EmailMatch,
    applications: list[dict]
) -> Optional[dict]:
    """Match an email to the most likely application.

    Args:
        email: The email to match
        applications: List of application dicts

    Returns:
        Best matching application or None
    """
    sender_lower = email.sender.lower()
    subject_lower = email.subject.lower()

    best_match = None
    best_score = 0

    for app in applications:
        company = app.get('company', '').lower()
        score = 0

        # Check sender domain matches company
        domain = infer_company_domain(app.get('company', ''))
        if domain and domain.lower() in sender_lower:
            score += 10

        # Check company name in sender
        if company in sender_lower:
            score += 5

        # Check company name in subject
        if company in subject_lower:
            score += 3

        # Check for ATS match with company name
        ats_patterns = ['greenhouse', 'lever', 'ashby', 'icims', 'workday', 'workable']
        if any(ats in sender_lower for ats in ats_patterns):
            if company in subject_lower or company in email.snippet.lower():
                score += 7

        if score > best_score:
            best_score = score
            best_match = app

    # Only return if we have a reasonable confidence
    if best_score >= 3:
        return best_match

    return None


def sync_application_emails(
    applications: list[dict],
    verbose: bool = False
) -> dict:
    """
    Sync emails to applications using the pairing system.

    For each application:
    1. Search for confirmation email if missing
    2. Search for resolution email if confirmed but unresolved
    3. Update pairing status

    Args:
        applications: List of application dicts
        verbose: Print progress if True

    Returns:
        Summary dict with counts of confirmations found, resolutions found, etc.
    """
    from datetime import timedelta

    from jj.db import (
        RESOLUTION_TO_STATUS,
        add_application_email,
        email_already_recorded,
        get_confirmation_email,
        get_resolution_email,
        transition_application_status,
        update_application_pairing_status,
    )

    client = GmailClient()
    client.authenticate()

    summary = {
        'applications_checked': 0,
        'confirmations_found': 0,
        'resolutions_found': 0,
        'already_resolved': 0,
        'errors': [],
        'details': [],
    }

    for app in applications:
        app_id = app.get('id')
        company = app.get('company', '')
        position = app.get('position', '')
        applied_at = app.get('applied_at')

        if not app_id:
            continue

        summary['applications_checked'] += 1

        if verbose:
            print(f"Syncing emails for {company} - {position}...")

        # Parse applied_at if string
        search_after = None
        if isinstance(applied_at, str) and applied_at:
            try:
                search_after = datetime.fromisoformat(applied_at.replace("Z", "+00:00"))
                # Search a day before to catch emails sent before application recorded
                search_after = search_after - timedelta(days=1)
            except ValueError:
                search_after = datetime.now() - timedelta(days=30)
        else:
            search_after = datetime.now() - timedelta(days=30)

        # Check current pairing state
        existing_confirmation = get_confirmation_email(app_id)
        existing_resolution = get_resolution_email(app_id)

        if existing_resolution:
            summary['already_resolved'] += 1
            if verbose:
                print("  Already resolved")
            update_application_pairing_status(app_id)
            continue

        # Search for emails from this company
        try:
            emails = client.search_for_company(
                company,
                after_date=search_after,
                search_type="update"  # Use update to catch all emails
            )
        except Exception as e:
            summary['errors'].append(f"{company}: {str(e)}")
            continue

        for email in emails:
            # Skip if already recorded
            if email_already_recorded(email.message_id):
                continue

            # Classify this email
            pair_type, resolution_type = classify_email_pair_type(email, app)

            if pair_type == 'unknown':
                continue

            # Record the email
            if pair_type == 'confirmation' and not existing_confirmation:
                add_application_email(
                    application_id=app_id,
                    email_type='confirmation',
                    received_at=email.date.isoformat(),
                    email_id=email.message_id,
                    sender=email.sender,
                    subject=email.subject,
                )
                existing_confirmation = True  # Mark as found for this run
                summary['confirmations_found'] += 1
                summary['details'].append({
                    'company': company,
                    'type': 'confirmation',
                    'subject': email.subject,
                    'date': email.date.isoformat(),
                })
                if verbose:
                    print(f"  Found confirmation: {email.subject}")

            elif pair_type == 'resolution' and not existing_resolution:
                # First positive response is always recruiter_screen, not interview
                # (Companies often say "interview" for initial recruiter calls)
                if resolution_type == 'interview':
                    resolution_type = 'screening'

                add_application_email(
                    application_id=app_id,
                    email_type='resolution',
                    resolution_type=resolution_type,
                    received_at=email.date.isoformat(),
                    email_id=email.message_id,
                    sender=email.sender,
                    subject=email.subject,
                )
                existing_resolution = True  # Mark as found for this run
                summary['resolutions_found'] += 1
                summary['details'].append({
                    'company': company,
                    'type': f'resolution ({resolution_type})',
                    'subject': email.subject,
                    'date': email.date.isoformat(),
                })
                if verbose:
                    print(f"  Found resolution ({resolution_type}): {email.subject}")

                # Auto-sync resolution to application status
                if resolution_type:
                    new_status = RESOLUTION_TO_STATUS.get(resolution_type)
                    if new_status:
                        transition_application_status(
                            app_id,
                            new_status,
                            reason=f"Email resolution: {resolution_type}",
                            source='email',
                            metadata={'email_id': email.message_id}
                        )
                        if verbose:
                            print(f"  Updated status to '{new_status}'")

        # Update pairing status
        update_application_pairing_status(app_id)

    return summary


def get_pairing_report(applications: list[dict]) -> str:
    """Generate a human-readable report of application email pairing status."""
    from jj.db import (
        get_pairing_stats,
    )

    stats = get_pairing_stats()

    lines = [
        "## Application Email Pairing Report",
        "",
        f"Total Applications: {stats['total']}",
        "",
        "### Status Breakdown",
        f"- Resolved (confirmation + resolution): {stats['resolved']}",
        f"- Confirmed (waiting for resolution): {stats['confirmed']}",
        f"- Ghosted (confirmed > 14 days, no resolution): {stats['ghosted']}",
        f"- Pending (recently applied, no confirmation yet): {stats['pending']}",
        f"- Unconfirmed (applied > 3 days, no confirmation): {stats['unconfirmed']}",
        "",
        "### Resolution Types",
        f"- Rejections: {stats['by_resolution_type']['rejection']}",
        f"- Screening calls: {stats['by_resolution_type']['screening']}",
        f"- Interviews: {stats['by_resolution_type']['interview']}",
        f"- Offers: {stats['by_resolution_type']['offer']}",
    ]

    return "\n".join(lines)
