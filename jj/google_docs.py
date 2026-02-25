"""Google Docs integration for resume generation.

This module provides:
- GoogleDocsClient: Wrapper for Google Docs and Drive APIs with authentication
- copy_template(): Copy a Google Docs template
- replace_text(): Make text replacements in a document
- export_pdf(): Export document as PDF
- generate_resume_gdocs(): High-level convenience function
- generate_resume_from_corpus(): Generate resume from corpus database
"""

import io
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from jj.config import JJ_HOME, load_config, load_profile, save_config

# Google API imports (with graceful fallback)
try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
    GDOCS_AVAILABLE = True
except ImportError:
    GDOCS_AVAILABLE = False


# OAuth scopes for Google Docs and Drive
SCOPES = [
    "https://www.googleapis.com/auth/documents",   # Read/write docs
    "https://www.googleapis.com/auth/drive",       # Full Drive access (needed to copy templates)
]

# Paths for credentials (shared credentials.json, separate token for Docs)
CREDENTIALS_PATH = JJ_HOME / "credentials.json"
GDOCS_TOKEN_PATH = JJ_HOME / "gdocs_token.json"


@dataclass
class ResumeGenerationResult:
    """Result of generating a resume via Google Docs."""
    success: bool
    doc_id: Optional[str] = None
    doc_url: Optional[str] = None
    pdf_path: Optional[Path] = None
    replacements_made: int = 0
    error: Optional[str] = None
    resume_id: Optional[int] = None


@dataclass
class CoverLetterGenerationResult:
    """Result of generating a cover letter via Google Docs."""
    success: bool
    doc_id: Optional[str] = None
    doc_url: Optional[str] = None
    pdf_path: Optional[Path] = None
    error: Optional[str] = None
    cover_letter_id: Optional[int] = None


@dataclass
class RoleData:
    """Data for a single role in a resume template."""
    role_id: int
    title: str
    company: str
    location: str
    date_range: str  # "Jan 2022 - Present"
    bullets: list[str] = field(default_factory=list)
    entry_ids: list[int] = field(default_factory=list)  # Track which entries were used


@dataclass
class ResumeTemplateData:
    """Complete data for populating a resume template."""
    profile: dict[str, Any]
    summary: str
    roles: list[RoleData]
    skills_by_category: dict[str, list[str]]


# Month abbreviations for date formatting
MONTH_NAMES = {
    "01": "Jan", "02": "Feb", "03": "Mar", "04": "Apr",
    "05": "May", "06": "Jun", "07": "Jul", "08": "Aug",
    "09": "Sep", "10": "Oct", "11": "Nov", "12": "Dec",
}


def format_date_range(start_date: Optional[str], end_date: Optional[str], is_current: bool) -> str:
    """Format YYYY-MM dates into a readable range like 'Jan 2022 - Present'.

    Args:
        start_date: Start date in YYYY-MM format (e.g., "2022-01")
        end_date: End date in YYYY-MM format or None
        is_current: Whether this is a current position

    Returns:
        Formatted date range string
    """
    def format_single(date_str: Optional[str]) -> str:
        if not date_str:
            return ""
        parts = date_str.split("-")
        if len(parts) >= 2:
            year = parts[0]
            month = MONTH_NAMES.get(parts[1], parts[1])
            return f"{month} {year}"
        return date_str

    start = format_single(start_date)
    if is_current or not end_date:
        end = "Present"
    else:
        end = format_single(end_date)

    if start and end:
        if start == end:
            return start
        return f"{start} - {end}"
    elif start:
        return start
    elif end:
        return end
    return ""


def assemble_template_data(
    variant: str = "general",
    max_roles: int = 5,
    max_bullets_per_role: int = 6,
) -> ResumeTemplateData:
    """Assemble all data needed to populate a resume template from the corpus.

    Args:
        variant: Summary variant to use (e.g., "growth", "ai-agentic", "general")
        max_roles: Maximum number of roles to include
        max_bullets_per_role: Maximum bullets per role

    Returns:
        ResumeTemplateData with all information needed for template population
    """
    from jj.db import (
        get_entries_for_role_ordered,
        get_roles_ordered_by_date,
        get_skills_by_category,
    )

    # Load profile
    profile = load_profile()

    # Get summary for the specified variant
    summaries = profile.get("summaries", {})
    summary = summaries.get(variant, summaries.get("general", ""))

    # Get roles ordered by date (most recent first)
    all_roles = get_roles_ordered_by_date(limit=max_roles)

    roles: list[RoleData] = []
    for role in all_roles:
        # Get entries for this role, ordered by times_used
        entries = get_entries_for_role_ordered(role["id"], limit=max_bullets_per_role)

        role_data = RoleData(
            role_id=role["id"],
            title=role.get("title", ""),
            company=role.get("company", ""),
            location=role.get("location", ""),
            date_range=format_date_range(
                role.get("start_date"),
                role.get("end_date"),
                role.get("is_current", False),
            ),
            bullets=[e["text"] for e in entries],
            entry_ids=[e["id"] for e in entries],
        )
        roles.append(role_data)

    # Get skills grouped by category
    skills_by_category = get_skills_by_category()

    return ResumeTemplateData(
        profile=profile,
        summary=summary,
        roles=roles,
        skills_by_category=skills_by_category,
    )


def build_replacement_dict(
    data: ResumeTemplateData,
    company: str,
    position: str,
    skill_categories: Optional[list[str]] = None,
    custom_skills: Optional[dict[str, list[str]]] = None,
) -> dict[str, str]:
    """Build the replacement dictionary for template placeholders.

    Args:
        data: Assembled template data from corpus
        company: Target company name
        position: Target position/role
        skill_categories: Optional ordered list of skill category keys to include.
                         If provided, only these categories are used, in this order.
                         Example: ["product-management", "technical", "leadership"]
        custom_skills: Optional dict mapping display names to skill lists.
                      Bypasses DB skills entirely when provided.
                      Example: {"AI & Orchestration": ["Agentic AI", "Multi-Agent Systems"]}

    Returns:
        Dictionary mapping placeholder strings to replacement values
    """
    replacements: dict[str, str] = {}

    # Target placeholders (support both UPPER and lower case)
    replacements["{{COMPANY}}"] = company
    replacements["{{company}}"] = company
    replacements["{{company_name}}"] = company
    replacements["{{POSITION}}"] = position
    replacements["{{position}}"] = position
    replacements["{{DATE}}"] = datetime.now().strftime("%B %d, %Y")
    replacements["{{date}}"] = datetime.now().strftime("%B %d, %Y")

    # Profile placeholders
    profile = data.profile
    name_data = profile.get("name", {})
    first_name = name_data.get("first", "")
    last_name = name_data.get("last", "")
    full_name = f"{first_name} {last_name}".strip()
    replacements["{{NAME}}"] = full_name

    contact = profile.get("contact", {})
    replacements["{{EMAIL}}"] = contact.get("email", "")
    replacements["{{PHONE}}"] = contact.get("phone", "")
    replacements["{{LOCATION}}"] = contact.get("location", "")

    links = profile.get("links", {})
    replacements["{{LINKEDIN}}"] = links.get("linkedin", "")
    replacements["{{GITHUB}}"] = links.get("github", "")

    # Summary (support both cases)
    replacements["{{SUMMARY}}"] = data.summary
    replacements["{{summary}}"] = data.summary

    # Experience placeholders (numbered by recency, 1-indexed)
    max_roles = 6  # Support up to 6 roles in template
    max_bullets = 6  # Support up to 6 bullets per role

    for role_num in range(1, max_roles + 1):
        role_prefix = f"{{{{ROLE_{role_num}_"

        if role_num <= len(data.roles):
            role = data.roles[role_num - 1]
            replacements[f"{role_prefix}TITLE}}}}"] = role.title
            replacements[f"{role_prefix}COMPANY}}}}"] = role.company
            replacements[f"{role_prefix}LOCATION}}}}"] = role.location
            replacements[f"{role_prefix}DATES}}}}"] = role.date_range

            # Bullets for this role
            for bullet_num in range(1, max_bullets + 1):
                if bullet_num <= len(role.bullets):
                    replacements[f"{role_prefix}BULLET_{bullet_num}}}}}"] = role.bullets[bullet_num - 1]
                else:
                    # Empty string for unused bullet slots
                    replacements[f"{role_prefix}BULLET_{bullet_num}}}}}"] = ""
        else:
            # Empty strings for unused role slots
            replacements[f"{role_prefix}TITLE}}}}"] = ""
            replacements[f"{role_prefix}COMPANY}}}}"] = ""
            replacements[f"{role_prefix}LOCATION}}}}"] = ""
            replacements[f"{role_prefix}DATES}}}}"] = ""
            for bullet_num in range(1, max_bullets + 1):
                replacements[f"{role_prefix}BULLET_{bullet_num}}}}}"] = ""

    # Section headers (conditionally shown based on whether roles are populated)
    # AI Consulting section only shown when Role 6 is populated
    replacements["{{SECTION_CONSULTING}}"] = "AI Consulting" if len(data.roles) >= 6 else ""

    # Skills placeholders - named categories (legacy)
    legacy_categories = ["technical", "domain", "leadership", "tools"]
    for cat in legacy_categories:
        placeholder = f"{{{{SKILLS_{cat.upper()}}}}}"
        skills_list = data.skills_by_category.get(cat, [])
        replacements[placeholder] = ", ".join(skills_list)

    # Skills placeholders - numbered categories (flexible template support)
    # Supports multiple formats: {{skills_category1}}, {{skill_category1}}, etc.
    # Priority: custom_skills > skill_categories > default DB order
    if custom_skills:
        # Use fully custom skills (display name → skill list)
        skill_items = list(custom_skills.items())
        for i, (display_name, skills_list) in enumerate(skill_items[:5], start=1):
            skills_str = ", ".join(skills_list)
            replacements[f"{{{{skills_category{i}}}}}"] = display_name
            replacements[f"{{{{skills_list{i}}}}}"] = skills_str
            replacements[f"{{{{skill_category{i}}}}}"] = display_name
            replacements[f"{{{{skill_list{i}}}}}"] = skills_str
            replacements[f"{{{{SKILLS_CATEGORY{i}}}}}"] = display_name
            replacements[f"{{{{SKILLS_LIST{i}}}}}"] = skills_str
        filled = len(skill_items)
    else:
        # Use DB skills with optional category ordering
        if skill_categories:
            ordered_categories = [c for c in skill_categories if c in data.skills_by_category]
        else:
            ordered_categories = list(data.skills_by_category.keys())

        for i, cat in enumerate(ordered_categories[:5], start=1):
            display_name = cat.replace("-", " ").replace("_", " ").title()
            skills_list = data.skills_by_category.get(cat, [])
            skills_str = ", ".join(skills_list)
            replacements[f"{{{{skills_category{i}}}}}"] = display_name
            replacements[f"{{{{skills_list{i}}}}}"] = skills_str
            replacements[f"{{{{skill_category{i}}}}}"] = display_name
            replacements[f"{{{{skill_list{i}}}}}"] = skills_str
            replacements[f"{{{{SKILLS_CATEGORY{i}}}}}"] = display_name
            replacements[f"{{{{SKILLS_LIST{i}}}}}"] = skills_str
        filled = len(ordered_categories)

    # Fill empty slots
    for i in range(filled + 1, 6):
        replacements[f"{{{{skills_category{i}}}}}"] = ""
        replacements[f"{{{{skills_list{i}}}}}"] = ""
        replacements[f"{{{{skill_category{i}}}}}"] = ""
        replacements[f"{{{{skill_list{i}}}}}"] = ""
        replacements[f"{{{{SKILLS_CATEGORY{i}}}}}"] = ""
        replacements[f"{{{{SKILLS_LIST{i}}}}}"] = ""

    return replacements


def _bold_skill_categories(client: "GoogleDocsClient", doc_id: str) -> int:
    """Bold skill category names in a generated resume document.

    Finds text like "Product Management:", "Technical:", etc. and applies bold formatting.
    This is needed because Google Docs text replacement doesn't preserve placeholder formatting.

    Args:
        client: Authenticated GoogleDocsClient
        doc_id: Document ID to modify

    Returns:
        Number of category names bolded
    """
    # Common skill category patterns to bold (everything up to and including ":")
    # These match the display names generated from category keys
    skill_patterns = [
        "Product Management:",
        "Technical:",
        "Leadership:",
        "Analytics & Tools:",
        "Growth & Experimentation:",
        "Ai & Orchestration:",
        "Health Tech:",
        # Add more patterns as needed
    ]

    doc = client.docs_service.documents().get(documentId=doc_id).execute()
    requests = []

    content = doc.get('body', {}).get('content', [])
    for element in content:
        if 'paragraph' in element:
            para = element['paragraph']
            for elem in para.get('elements', []):
                text_run = elem.get('textRun', {})
                text = text_run.get('content', '')
                start = elem.get('startIndex')

                for pattern in skill_patterns:
                    if pattern in text:
                        keyword_start = text.find(pattern)
                        if keyword_start >= 0:
                            abs_start = start + keyword_start
                            abs_end = abs_start + len(pattern)
                            requests.append({
                                'updateTextStyle': {
                                    'range': {'startIndex': abs_start, 'endIndex': abs_end},
                                    'textStyle': {'bold': True},
                                    'fields': 'bold'
                                }
                            })

    if requests:
        client.docs_service.documents().batchUpdate(
            documentId=doc_id,
            body={'requests': requests}
        ).execute()

    return len(requests)


def generate_resume_from_corpus(
    company: str,
    position: str,
    variant: str = "general",
    custom_summary: Optional[str] = None,
    skill_categories: Optional[list[str]] = None,
    custom_skills: Optional[dict[str, list[str]]] = None,
    role_bullets: Optional[dict[str, list[str]]] = None,
    max_roles: int = 5,
    max_bullets_per_role: int = 6,
    template_id: Optional[str] = None,
    output_dir: Optional[Path] = None,
    auto_open: bool = True,
    keep_google_doc: bool = True,
) -> ResumeGenerationResult:
    """Generate a resume from corpus data using Google Docs.

    This is the main entry point for corpus-based resume generation. It:
    1. Assembles data from the corpus database
    2. Builds replacement dictionary for all placeholders
    3. Copies the template, replaces text, exports PDF
    4. Tracks usage in the database (resumes + resume_entries tables)
    5. Increments times_used on selected entries

    Args:
        company: Target company name
        position: Target position title
        variant: Summary variant to use (e.g., "growth", "ai-agentic")
        custom_summary: Custom summary text (overrides variant summary if provided)
        skill_categories: Ordered list of skill category keys to include (e.g.,
                         ["product-management", "technical", "leadership"]).
                         If None, uses all categories in default order.
        custom_skills: Custom skills section. Dict mapping display names to skill
                      lists, bypassing DB skills entirely. Example:
                      {"AI & Orchestration": ["Agentic AI", "Multi-Agent Systems"]}
        role_bullets: Custom bullet selection per role. Dict mapping company name
                     to ordered list of bullet texts. Each bullet is matched against
                     corpus entries by prefix. Overrides auto-selection for matched
                     roles. Example: {"ZenBusiness, Inc.": ["Integrated AI...", ...]}
        max_roles: Maximum number of roles to include
        max_bullets_per_role: Maximum bullets per role
        template_id: Google Docs template ID (uses config default if not provided)
        output_dir: Directory for PDF output (uses config default if not provided)
        auto_open: Whether to open the PDF after generation
        keep_google_doc: Whether to keep the Google Doc (vs delete after PDF export)

    Returns:
        ResumeGenerationResult with details of the operation
    """
    from jj.db import (
        create_resume,
        create_resume_entry,
        create_resume_section,
        get_connection,
        increment_entry_usage,
    )

    # Get config defaults
    config = get_gdocs_config()

    if template_id is None:
        template_id = config.get("template_id")
        if not template_id:
            return ResumeGenerationResult(
                success=False,
                error="No template ID configured. Set with: jj gdocs config --template-id YOUR_ID"
            )

    if output_dir is None:
        output_dir_str = config.get("pdf_output_dir", "~/Documents/Resumes")
        output_dir = Path(output_dir_str).expanduser()

    # Assemble data from corpus
    try:
        data = assemble_template_data(
            variant=variant,
            max_roles=max_roles,
            max_bullets_per_role=max_bullets_per_role,
        )
    except Exception as e:
        return ResumeGenerationResult(success=False, error=f"Error assembling corpus data: {e}")

    # Override bullets per role if custom selection provided
    if role_bullets:
        with get_connection() as conn:
            for role in data.roles:
                if role.company not in role_bullets:
                    continue
                custom_texts = role_bullets[role.company]
                new_bullets = []
                new_entry_ids = []
                for bullet_text in custom_texts:
                    # Match by prefix (first 60 chars) against entries for this role
                    prefix = bullet_text[:60]
                    row = conn.execute(
                        "SELECT id, text FROM entries WHERE text LIKE ? AND role_id = ?",
                        (prefix + "%", role.role_id),
                    ).fetchone()
                    if row:
                        new_bullets.append(row["text"])
                        new_entry_ids.append(row["id"])
                role.bullets = new_bullets
                role.entry_ids = new_entry_ids

    # Build replacement dictionary
    replacements = build_replacement_dict(data, company, position, skill_categories, custom_skills)

    # Override summary if custom_summary provided
    if custom_summary:
        replacements["{{SUMMARY}}"] = custom_summary
        replacements["{{summary}}"] = custom_summary

    # Get name from profile for document naming
    name_data = data.profile.get("name", {})
    full_name = f"{name_data.get('first', '')} {name_data.get('last', '')}".strip() or "Resume"

    # Build document title
    timestamp = datetime.now().strftime("%Y%m%d")
    doc_title = f"{full_name} - {position} - {company} - {timestamp}"

    # Build filename for PDF
    pdf_filename = f"{full_name} - {position} - {company} - Resume.pdf"
    pdf_path = output_dir / pdf_filename

    try:
        client = GoogleDocsClient()
        client.authenticate()

        # Copy template
        doc_id = client.copy_template(template_id, doc_title)
        doc_url = client.get_document_url(doc_id)

        # Make replacements
        replacements_made = client.replace_text(doc_id, replacements)

        # Clean up empty sections from unused role slots
        client.cleanup_empty_sections(doc_id)

        # Bold skill category names (formatting isn't preserved through replacement)
        _bold_skill_categories(client, doc_id)

        # Export PDF
        client.export_pdf(doc_id, pdf_path)

        # Optionally delete the Google Doc
        final_doc_id = doc_id
        final_doc_url = doc_url
        if not keep_google_doc:
            client.delete_document(doc_id)
            final_doc_id = None
            final_doc_url = None

        # Track in database (use custom_summary if provided, else variant summary)
        resume_id = create_resume(
            filename=pdf_path.name,
            filepath=str(pdf_path),
            variant=variant,
            summary_text=custom_summary if custom_summary else data.summary,
            target_company=company,
            target_role=position,
            google_doc_id=doc_id if keep_google_doc else None,
        )

        # Track each entry used and increment times_used
        for role in data.roles:
            for position_idx, entry_id in enumerate(role.entry_ids):
                create_resume_entry(
                    resume_id=resume_id,
                    entry_id=entry_id,
                    role_id=role.role_id,
                    position=position_idx,
                )
                increment_entry_usage(entry_id)

        # Track summary variant used
        create_resume_section(
            resume_id=resume_id,
            section_type="summary",
            section_name=variant,
            content=data.summary,
        )

        # Track skills used
        for category, skills in data.skills_by_category.items():
            if skills:
                create_resume_section(
                    resume_id=resume_id,
                    section_type="skills",
                    section_name=category,
                    content=", ".join(skills),
                )

        # Optionally open the PDF
        if auto_open and pdf_path.exists():
            open_file(pdf_path)

        return ResumeGenerationResult(
            success=True,
            doc_id=final_doc_id,
            doc_url=final_doc_url,
            pdf_path=pdf_path,
            replacements_made=replacements_made,
            resume_id=resume_id,
        )

    except FileNotFoundError as e:
        return ResumeGenerationResult(success=False, error=str(e))
    except Exception as e:
        return ResumeGenerationResult(success=False, error=f"API error: {e}")


def generate_cover_letter(
    company: str,
    position: str,
    paragraphs: list[str],
    interest_id: Optional[int] = None,
    output_dir: Optional[Path] = None,
    auto_open: bool = True,
    keep_google_doc: bool = True,
) -> CoverLetterGenerationResult:
    """Generate a cover letter as a Google Doc and export to PDF.

    Unlike resume generation (template-based), cover letters are created as
    fresh Google Docs with formatted content composed by the caller.

    Args:
        company: Target company name
        position: Target position title
        paragraphs: List of 3-4 paragraph strings for the letter body
        interest_id: ID of the interest used as a hook (for tracking)
        output_dir: Directory for PDF output (uses config default if not provided)
        auto_open: Whether to open the PDF after generation
        keep_google_doc: Whether to keep the Google Doc after export

    Returns:
        CoverLetterGenerationResult with details of the operation
    """
    from jj.db import create_cover_letter, increment_interest_usage

    config = get_gdocs_config()

    if output_dir is None:
        output_dir_str = config.get("pdf_output_dir", "~/Documents/Resumes")
        output_dir = Path(output_dir_str).expanduser()

    # Load profile for header
    profile = load_profile()
    name_data = profile.get("name", {})
    full_name = f"{name_data.get('first', '')} {name_data.get('last', '')}".strip()
    contact = profile.get("contact", {})
    email = contact.get("email", "")
    phone = contact.get("phone", "")
    location = contact.get("location", "")
    links = profile.get("links", {})
    linkedin = links.get("linkedin", "")

    # Build the cover letter text
    date_str = datetime.now().strftime("%B %d, %Y")

    lines = [
        full_name,
        f"{email} | {phone} | {location}",
        linkedin,
        "",
        date_str,
        "",
        "Dear Hiring Team,",
        "",
    ]

    for i, para in enumerate(paragraphs):
        lines.append(para)
        if i < len(paragraphs) - 1:
            lines.append("")

    lines.extend(["", "Best,", full_name])

    full_text = "\n".join(lines)

    # Build filenames
    pdf_filename = f"{full_name} - {position} - {company} - Cover Letter.pdf"
    pdf_path = output_dir / pdf_filename
    timestamp = datetime.now().strftime("%Y%m%d")
    doc_title = f"{full_name} - {position} - {company} - Cover Letter - {timestamp}"

    try:
        client = GoogleDocsClient()
        client.authenticate()

        # Create fresh document and insert text
        doc_id = client.create_document(doc_title)
        doc_url = client.get_document_url(doc_id)
        client.insert_text(doc_id, full_text)

        # Apply formatting
        # Calculate character ranges from the known text structure
        name_end = len(full_name) + 1  # +1 for newline
        contact_line = f"{email} | {phone} | {location}"
        contact_end = name_end + len(contact_line) + 1
        linkedin_end = contact_end + len(linkedin) + 1
        # Total text length (index 1 is the start in Google Docs)
        text_len = len(full_text)

        formatting_requests = [
            # Set entire document font (Garamond, 11pt)
            {
                "updateTextStyle": {
                    "range": {"startIndex": 1, "endIndex": 1 + text_len},
                    "textStyle": {
                        "weightedFontFamily": {"fontFamily": "Garamond"},
                        "fontSize": {"magnitude": 11, "unit": "PT"},
                    },
                    "fields": "weightedFontFamily,fontSize",
                }
            },
            # Name: 14pt bold
            {
                "updateTextStyle": {
                    "range": {"startIndex": 1, "endIndex": 1 + len(full_name)},
                    "textStyle": {
                        "bold": True,
                        "fontSize": {"magnitude": 14, "unit": "PT"},
                    },
                    "fields": "bold,fontSize",
                }
            },
            # Contact line: 10pt
            {
                "updateTextStyle": {
                    "range": {"startIndex": 1 + name_end, "endIndex": 1 + contact_end - 1},
                    "textStyle": {
                        "fontSize": {"magnitude": 10, "unit": "PT"},
                    },
                    "fields": "fontSize",
                }
            },
            # LinkedIn: 10pt
            {
                "updateTextStyle": {
                    "range": {"startIndex": 1 + contact_end, "endIndex": 1 + linkedin_end - 1},
                    "textStyle": {
                        "fontSize": {"magnitude": 10, "unit": "PT"},
                    },
                    "fields": "fontSize",
                }
            },
            # Line spacing for entire doc: 1.15
            {
                "updateParagraphStyle": {
                    "range": {"startIndex": 1, "endIndex": 1 + text_len},
                    "paragraphStyle": {
                        "lineSpacing": 115,
                        "spaceBelow": {"magnitude": 6, "unit": "PT"},
                    },
                    "fields": "lineSpacing,spaceBelow",
                }
            },
        ]

        client.apply_formatting(doc_id, formatting_requests)

        # Export PDF
        client.export_pdf(doc_id, pdf_path)

        # Optionally delete the Google Doc
        final_doc_id = doc_id
        final_doc_url = doc_url
        if not keep_google_doc:
            client.delete_document(doc_id)
            final_doc_id = None
            final_doc_url = None

        # Track in database
        cl_id = create_cover_letter(
            filename=pdf_path.name,
            filepath=str(pdf_path),
            target_company=company,
            target_role=position,
            interest_id=interest_id,
            google_doc_id=doc_id if keep_google_doc else None,
        )

        # Track interest usage
        if interest_id:
            increment_interest_usage(interest_id)

        # Optionally open the PDF
        if auto_open and pdf_path.exists():
            open_file(pdf_path)

        return CoverLetterGenerationResult(
            success=True,
            doc_id=final_doc_id,
            doc_url=final_doc_url,
            pdf_path=pdf_path,
            cover_letter_id=cl_id,
        )

    except Exception as e:
        return CoverLetterGenerationResult(success=False, error=f"API error: {e}")


def get_all_placeholders() -> dict[str, list[str]]:
    """Get all supported template placeholders grouped by category.

    Returns:
        Dictionary with categories as keys and lists of placeholders as values.
    """
    placeholders: dict[str, list[str]] = {
        "Profile": [
            "{{NAME}}",
            "{{EMAIL}}",
            "{{PHONE}}",
            "{{LOCATION}}",
            "{{LINKEDIN}}",
            "{{GITHUB}}",
        ],
        "Summary": [
            "{{SUMMARY}}",
        ],
        "Target": [
            "{{COMPANY}}",
            "{{POSITION}}",
            "{{DATE}}",
        ],
        "Skills": [
            "{{SKILLS_TECHNICAL}}",
            "{{SKILLS_DOMAIN}}",
            "{{SKILLS_LEADERSHIP}}",
            "{{SKILLS_TOOLS}}",
        ],
    }

    # Add experience placeholders for up to 6 roles with 6 bullets each
    experience: list[str] = []
    for role_num in range(1, 7):
        experience.extend([
            f"{{{{ROLE_{role_num}_TITLE}}}}",
            f"{{{{ROLE_{role_num}_COMPANY}}}}",
            f"{{{{ROLE_{role_num}_LOCATION}}}}",
            f"{{{{ROLE_{role_num}_DATES}}}}",
        ])
        for bullet_num in range(1, 7):
            experience.append(f"{{{{ROLE_{role_num}_BULLET_{bullet_num}}}}}")

    placeholders["Experience"] = experience

    return placeholders


def get_gdocs_config() -> dict:
    """Get Google Docs configuration from config.yaml."""
    config = load_config()
    return config.get("google_docs", {})


def save_gdocs_config(
    template_id: Optional[str] = None,
    pdf_output_dir: Optional[str] = None,
    auto_open: Optional[bool] = None,
    keep_google_doc: Optional[bool] = None,
) -> None:
    """Save Google Docs configuration to config.yaml."""
    config = load_config()

    if "google_docs" not in config:
        config["google_docs"] = {}

    if template_id is not None:
        config["google_docs"]["template_id"] = template_id
    if pdf_output_dir is not None:
        config["google_docs"]["pdf_output_dir"] = pdf_output_dir
    if auto_open is not None:
        config["google_docs"]["auto_open"] = auto_open
    if keep_google_doc is not None:
        config["google_docs"]["keep_google_doc"] = keep_google_doc

    save_config(config)


class GoogleDocsClient:
    """Client for Google Docs and Drive API operations."""

    def __init__(self):
        """Initialize the Google Docs client."""
        if not GDOCS_AVAILABLE:
            raise ImportError(
                "Google API dependencies not installed. Install with:\n"
                "pip install google-api-python-client google-auth-oauthlib"
            )

        self.docs_service = None
        self.drive_service = None
        self._creds = None

    def authenticate(self) -> bool:
        """Authenticate with Google APIs. Returns True if successful."""
        creds = None

        # Load existing token
        if GDOCS_TOKEN_PATH.exists():
            creds = Credentials.from_authorized_user_file(str(GDOCS_TOKEN_PATH), SCOPES)

        # Refresh or get new credentials
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not CREDENTIALS_PATH.exists():
                    raise FileNotFoundError(
                        f"Google credentials not found at {CREDENTIALS_PATH}.\n"
                        f"Copy credentials.json from your Google Cloud Console project to {JJ_HOME}"
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(CREDENTIALS_PATH), SCOPES
                )
                creds = flow.run_local_server(port=0)

            # Save refreshed/new token
            with open(GDOCS_TOKEN_PATH, "w") as f:
                f.write(creds.to_json())

        self._creds = creds
        self.docs_service = build("docs", "v1", credentials=creds)
        self.drive_service = build("drive", "v3", credentials=creds)
        return True

    def _ensure_authenticated(self) -> None:
        """Ensure we're authenticated before making API calls."""
        if not self.docs_service or not self.drive_service:
            self.authenticate()

    def copy_template(self, template_id: str, title: str) -> str:
        """Copy a Google Docs template and return the new document ID.

        Args:
            template_id: The ID of the template document to copy
            title: The title for the new document

        Returns:
            The document ID of the new copy
        """
        self._ensure_authenticated()

        result = self.drive_service.files().copy(
            fileId=template_id,
            body={"name": title}
        ).execute()

        return result["id"]

    def create_document(self, title: str) -> str:
        """Create a new blank Google Doc and return its ID."""
        self._ensure_authenticated()
        doc = self.docs_service.documents().create(
            body={"title": title}
        ).execute()
        return doc["documentId"]

    def insert_text(self, doc_id: str, text: str, index: int = 1) -> None:
        """Insert text at a position in the document."""
        self._ensure_authenticated()
        self.docs_service.documents().batchUpdate(
            documentId=doc_id,
            body={"requests": [{
                "insertText": {
                    "location": {"index": index},
                    "text": text,
                }
            }]},
        ).execute()

    def apply_formatting(self, doc_id: str, requests: list[dict]) -> None:
        """Apply a batch of formatting requests to a document."""
        self._ensure_authenticated()
        if requests:
            self.docs_service.documents().batchUpdate(
                documentId=doc_id,
                body={"requests": requests},
            ).execute()

    def replace_text(self, doc_id: str, replacements: dict[str, str]) -> int:
        """Replace text placeholders in a document.

        Args:
            doc_id: The document ID to modify
            replacements: Dict mapping placeholder text to replacement text

        Returns:
            Total number of replacements made
        """
        self._ensure_authenticated()

        if not replacements:
            return 0

        requests = []
        for old_text, new_text in replacements.items():
            requests.append({
                "replaceAllText": {
                    "containsText": {
                        "text": old_text,
                        "matchCase": True,
                    },
                    "replaceText": new_text,
                }
            })

        result = self.docs_service.documents().batchUpdate(
            documentId=doc_id,
            body={"requests": requests}
        ).execute()

        # Count total replacements made
        total_replacements = 0
        for reply in result.get("replies", []):
            replace_result = reply.get("replaceAllText", {})
            total_replacements += replace_result.get("occurrencesChanged", 0)

        return total_replacements

    def cleanup_empty_sections(self, doc_id: str) -> int:
        """Remove empty role artifacts left after placeholder replacement.

        When roles 5-6 are unused, replacing their placeholders with empty
        strings leaves behind commas, empty bullets, and blank lines.
        This method reads the document and deletes those empty paragraphs.

        Args:
            doc_id: The document ID to clean up

        Returns:
            Number of paragraphs deleted
        """
        self._ensure_authenticated()

        doc = self.docs_service.documents().get(documentId=doc_id).execute()
        body = doc.get("body", {})
        content = body.get("content", [])

        # Find the body's end index (the trailing newline we can't delete)
        body_end = content[-1]["endIndex"] if content else 0

        # Collect paragraph ranges to delete (must delete in reverse order)
        delete_ranges = []
        for element in content:
            if "paragraph" not in element:
                continue

            para = element["paragraph"]
            text = ""
            for elem in para.get("elements", []):
                text += elem.get("textRun", {}).get("content", "")

            stripped = text.strip()
            is_list_item = "bullet" in para

            # Only delete artifacts from empty role slots, not intentional spacing:
            # - Comma-only lines (from empty "{{COMPANY}}, {{LOCATION}}")
            # - Empty bullet list items (from empty "{{BULLET_N}}")
            # Intentional blank lines (non-list, no comma) are preserved.
            if stripped == "," or (stripped == "" and is_list_item):
                start = element["startIndex"]
                end = element["endIndex"]
                delete_ranges.append((start, end))

        if not delete_ranges:
            return 0

        # Delete in reverse order so indices don't shift
        delete_ranges.sort(key=lambda r: r[0], reverse=True)

        requests = []
        for start, end in delete_ranges:
            # Don't delete the very first element (index 0-1 is the doc body start)
            if start < 2:
                continue
            # Can't delete the body's final newline — shrink range by 1
            if end >= body_end:
                end = body_end - 1
                if end <= start:
                    continue
            requests.append({
                "deleteContentRange": {
                    "range": {
                        "startIndex": start,
                        "endIndex": end,
                    }
                }
            })

        if not requests:
            return 0

        # Try batch delete; if it fails, fall back to one-at-a-time
        try:
            self.docs_service.documents().batchUpdate(
                documentId=doc_id,
                body={"requests": requests},
            ).execute()
            return len(requests)
        except Exception:
            # Some ranges may span structural boundaries — delete individually
            deleted = 0
            for req in requests:
                try:
                    self.docs_service.documents().batchUpdate(
                        documentId=doc_id,
                        body={"requests": [req]},
                    ).execute()
                    deleted += 1
                except Exception:
                    pass  # Skip invalid ranges
            return deleted

    def export_pdf(self, doc_id: str, output_path: Path) -> Path:
        """Export a document as PDF.

        Args:
            doc_id: The document ID to export
            output_path: Path where the PDF should be saved

        Returns:
            The path to the saved PDF file
        """
        self._ensure_authenticated()

        # Ensure parent directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        request = self.drive_service.files().export_media(
            fileId=doc_id,
            mimeType="application/pdf"
        )

        # Download the file
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)

        done = False
        while not done:
            status, done = downloader.next_chunk()

        # Write to file
        with open(output_path, "wb") as f:
            f.write(fh.getvalue())

        return output_path

    def get_document(self, doc_id: str) -> dict:
        """Get document metadata and content.

        Args:
            doc_id: The document ID to retrieve

        Returns:
            Document object from the API
        """
        self._ensure_authenticated()

        return self.docs_service.documents().get(documentId=doc_id).execute()

    def delete_document(self, doc_id: str) -> bool:
        """Delete a document (move to trash).

        Args:
            doc_id: The document ID to delete

        Returns:
            True if successful
        """
        self._ensure_authenticated()

        self.drive_service.files().delete(fileId=doc_id).execute()
        return True

    def get_document_url(self, doc_id: str) -> str:
        """Get the URL to open a document in Google Docs.

        Args:
            doc_id: The document ID

        Returns:
            URL string
        """
        return f"https://docs.google.com/document/d/{doc_id}/edit"


def generate_resume_gdocs(
    company: str,
    position: str,
    template_id: Optional[str] = None,
    output_dir: Optional[Path] = None,
    replacements: Optional[dict[str, str]] = None,
    auto_open: bool = True,
    keep_google_doc: bool = True,
) -> ResumeGenerationResult:
    """High-level function to generate a resume from a Google Docs template.

    Args:
        company: Target company name
        position: Target position title
        template_id: Google Docs template ID (uses config default if not provided)
        output_dir: Directory for PDF output (uses config default if not provided)
        replacements: Additional text replacements to make
        auto_open: Whether to open the PDF after generation
        keep_google_doc: Whether to keep the Google Doc (vs delete after PDF export)

    Returns:
        ResumeGenerationResult with details of the operation
    """
    # Get config defaults
    config = get_gdocs_config()

    if template_id is None:
        template_id = config.get("template_id")
        if not template_id:
            return ResumeGenerationResult(
                success=False,
                error="No template ID configured. Set with: jj gdocs config --template-id YOUR_ID"
            )

    if output_dir is None:
        output_dir_str = config.get("pdf_output_dir", "~/Documents/Resumes")
        output_dir = Path(output_dir_str).expanduser()

    # Build document title
    timestamp = datetime.now().strftime("%Y%m%d")
    doc_title = f"{company} - {position} - Resume - {timestamp}"

    # Build filename for PDF
    pdf_filename = f"{company} - {position} - Resume.pdf"
    pdf_path = output_dir / pdf_filename

    # Build default replacements
    default_replacements = {
        "{{COMPANY}}": company,
        "{{POSITION}}": position,
        "{{DATE}}": datetime.now().strftime("%B %d, %Y"),
    }

    # Merge with custom replacements
    all_replacements = {**default_replacements, **(replacements or {})}

    try:
        client = GoogleDocsClient()
        client.authenticate()

        # Copy template
        doc_id = client.copy_template(template_id, doc_title)
        doc_url = client.get_document_url(doc_id)

        # Make replacements
        replacements_made = client.replace_text(doc_id, all_replacements)

        # Export PDF
        client.export_pdf(doc_id, pdf_path)

        # Optionally delete the Google Doc
        if not keep_google_doc:
            client.delete_document(doc_id)
            doc_id = None
            doc_url = None

        # Optionally open the PDF
        if auto_open and pdf_path.exists():
            open_file(pdf_path)

        return ResumeGenerationResult(
            success=True,
            doc_id=doc_id,
            doc_url=doc_url,
            pdf_path=pdf_path,
            replacements_made=replacements_made,
        )

    except FileNotFoundError as e:
        return ResumeGenerationResult(success=False, error=str(e))
    except Exception as e:
        return ResumeGenerationResult(success=False, error=f"API error: {e}")


def open_file(path: Path) -> None:
    """Open a file with the system default application."""
    if sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)
    elif sys.platform == "win32":
        os.startfile(str(path))
    else:
        subprocess.run(["xdg-open", str(path)], check=False)


def open_url(url: str) -> None:
    """Open a URL in the default browser."""
    import webbrowser
    webbrowser.open(url)


def test_connection() -> tuple[bool, str]:
    """Test the Google Docs API connection.

    Returns:
        Tuple of (success, message)
    """
    try:
        client = GoogleDocsClient()
        client.authenticate()

        # Try to access Drive to verify connection
        about = client.drive_service.about().get(fields="user").execute()
        user_email = about.get("user", {}).get("emailAddress", "unknown")

        return True, f"Connected as: {user_email}"
    except FileNotFoundError as e:
        return False, str(e)
    except Exception as e:
        return False, f"Connection failed: {e}"
