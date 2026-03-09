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


def _extract_jd_keywords(jd_text: str) -> set[str]:
    """Extract meaningful keywords from job description text.

    Tokenizes the JD, removes stop words, and returns a set of lowercase
    keywords (single words and bigrams) for bullet relevance scoring.
    """
    import re

    stop_words = {
        "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
        "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
        "being", "have", "has", "had", "do", "does", "did", "will", "would",
        "could", "should", "may", "might", "shall", "can", "need", "must",
        "it", "its", "this", "that", "these", "those", "we", "you", "your",
        "our", "they", "their", "them", "who", "what", "which", "when",
        "where", "how", "not", "no", "if", "as", "so", "than", "too", "very",
        "just", "about", "also", "into", "over", "such", "all", "any", "each",
        "every", "both", "few", "more", "most", "other", "some", "up", "out",
        "new", "work", "role", "team", "ability", "experience", "years",
        "strong", "including", "across", "within", "well", "etc", "e.g",
    }

    # Normalize: lowercase, replace punctuation with spaces
    text = re.sub(r"[^a-z0-9\s/+#.-]", " ", jd_text.lower())
    words = [w for w in text.split() if w not in stop_words and len(w) > 2]

    keywords = set(words)

    # Add bigrams for multi-word terms (e.g., "product management", "a/b testing")
    for i in range(len(words) - 1):
        keywords.add(f"{words[i]} {words[i+1]}")

    return keywords


def _score_bullet_relevance(
    bullet_text: str,
    bullet_tags: list[str],
    jd_keywords: set[str],
) -> float:
    """Score a bullet's relevance to a job description.

    Returns a score from 0.0 to 1.0 based on keyword overlap between the
    bullet text/tags and extracted JD keywords.
    """
    import re

    # Normalize bullet text
    bullet_lower = re.sub(r"[^a-z0-9\s/+#.-]", " ", bullet_text.lower())
    bullet_words = set(bullet_lower.split())

    # Build bullet bigrams
    word_list = bullet_lower.split()
    bullet_bigrams = {f"{word_list[i]} {word_list[i+1]}" for i in range(len(word_list) - 1)}

    # Score: count JD keywords found in bullet text or tags
    tag_set = {t.lower() for t in bullet_tags}
    matches = 0
    for kw in jd_keywords:
        if " " in kw:
            # Bigram: check in bullet bigrams
            if kw in bullet_bigrams:
                matches += 1.5  # Bigram matches are worth more
        else:
            if kw in bullet_words or kw in tag_set:
                matches += 1.0

    # Normalize by JD keyword count to get 0-1 range
    if not jd_keywords:
        return 0.0
    return min(matches / len(jd_keywords), 1.0)


def assemble_template_data(
    variant: str = "general",
    max_roles: int = 5,
    max_bullets_per_role: int = 6,
    jd_text: Optional[str] = None,
) -> ResumeTemplateData:
    """Assemble all data needed to populate a resume template from the corpus.

    Args:
        variant: Summary variant to use (e.g., "growth", "ai-agentic", "general")
        max_roles: Maximum number of roles to include
        max_bullets_per_role: Maximum bullets per role
        jd_text: Optional job description text for relevance-based bullet ranking

    Returns:
        ResumeTemplateData with all information needed for template population
    """
    import json

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

    # Extract JD keywords if JD text provided
    jd_keywords = _extract_jd_keywords(jd_text) if jd_text else None

    # Get roles ordered by date (most recent first)
    all_roles = get_roles_ordered_by_date(limit=max_roles)

    roles: list[RoleData] = []
    for role in all_roles:
        if jd_keywords:
            # Fetch ALL entries for this role, score by JD relevance, take top N
            all_entries = get_entries_for_role_ordered(role["id"], limit=None)
            scored = []
            for e in all_entries:
                tags = json.loads(e.get("tags", "[]")) if isinstance(e.get("tags"), str) else (e.get("tags") or [])
                score = _score_bullet_relevance(e["text"], tags, jd_keywords)
                scored.append((score, e))
            # Sort by relevance (desc), then times_used (desc) as tiebreaker
            scored.sort(key=lambda x: (x[0], x[1].get("times_used", 0)), reverse=True)
            entries = [e for _, e in scored[:max_bullets_per_role]]
        else:
            # Default: ordered by times_used
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
    # The consulting block covers TWO roles: "AI Health-Tech Startup" and
    # "Clearhead / Accenture Interactive". These are consulting stints that
    # belong in the consulting section (Role 6), NOT the main experience body.
    # If the AI Health-Tech role is already in Roles 1-5, the entire consulting
    # section stays empty (don't show either consulting role).
    consulting_companies = {"AI Health-Tech Startup", "Clearhead / Accenture Interactive"}
    consulting_in_main_body = any(
        r.company in consulting_companies for r in data.roles[:5]
    )
    show_consulting = (
        len(data.roles) >= 6
        and not consulting_in_main_body
        and data.roles[5].company in consulting_companies
    )
    replacements["{{SECTION_CONSULTING}}"] = "AI Consulting" if show_consulting else ""

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

        # Flatten multi-column sections to single-column (ATS can't parse columns)
        client.flatten_column_sections(doc_id)

        # Flatten any tables to simple paragraphs (ATS can't parse tables)
        client.flatten_tables(doc_id)

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


@dataclass
class _Segment:
    """A piece of resume text with its formatting type."""
    text: str
    kind: str  # "name", "contact", "links", "section_header", "summary",
               # "role_header", "role_location", "bullet", "edu_degree",
               # "edu_school", "edu_details", "skills_line", "blank"
    bold_prefix_len: int = 0  # For skills_line: bold up to the colon


def _build_resume_segments(
    data: ResumeTemplateData,
    resolved_skills: dict[str, list[str]],
    show_consulting: bool,
) -> list[_Segment]:
    """Build the ordered list of text segments for a resume.

    Args:
        data: Assembled template data from corpus
        resolved_skills: Display name -> skill list (already resolved)
        show_consulting: Whether to include the consulting section

    Returns:
        Ordered list of _Segment objects
    """
    profile = data.profile
    name_data = profile.get("name", {})
    full_name = f"{name_data.get('first', '')} {name_data.get('last', '')}".strip()

    contact = profile.get("contact", {})
    email = contact.get("email", "")
    phone = contact.get("phone", "")
    location = contact.get("location", "")
    contact_parts = [p for p in [email, phone, location] if p]
    contact_line = " | ".join(contact_parts)

    links = profile.get("links", {})
    link_parts = [v for v in [links.get("linkedin", ""), links.get("github", "")] if v]
    links_line = " | ".join(link_parts)

    segments: list[_Segment] = []

    # Header
    segments.append(_Segment(full_name, "name"))
    if contact_line:
        segments.append(_Segment(contact_line, "contact"))
    if links_line:
        segments.append(_Segment(links_line, "links"))

    # Summary (join multiple lines into a single paragraph)
    segments.append(_Segment("", "blank"))
    segments.append(_Segment("SUMMARY", "section_header"))
    if data.summary:
        # Collapse newlines into spaces for a single-paragraph summary
        summary_text = " ".join(data.summary.split("\n"))
        summary_text = " ".join(summary_text.split())  # Normalize whitespace
        segments.append(_Segment(summary_text, "summary"))

    # Experience
    segments.append(_Segment("", "blank"))
    segments.append(_Segment("EXPERIENCE", "section_header"))

    # Determine which roles go in main body vs consulting
    main_roles = data.roles[:5]  # Up to 5 main roles
    consulting_role = data.roles[5] if len(data.roles) >= 6 and show_consulting else None

    for role_idx, role in enumerate(main_roles):
        if not role.company and not role.title:
            continue  # Skip empty role slots

        # Role header line 1: "Company, Location | Date Range"
        header_parts = [role.company]
        if role.location:
            header_parts[0] += f", {role.location}"
        if role.date_range:
            header_parts.append(role.date_range)
        header = " | ".join(header_parts)
        segments.append(_Segment(header, "role_header"))

        # Role title on its own line
        if role.title:
            segments.append(_Segment(role.title, "role_title"))

        # Bullets (use text prefix, not Google Docs list formatting)
        for bullet in role.bullets:
            if bullet:
                segments.append(_Segment(f"• {bullet}", "bullet"))

        # Spacer between roles (but not after the last one before next section)
        if role_idx < len(main_roles) - 1:
            segments.append(_Segment("", "blank"))

    # Consulting section
    if consulting_role and consulting_role.company:
        segments.append(_Segment("", "blank"))
        segments.append(_Segment("AI CONSULTING", "section_header"))
        header_parts = [consulting_role.company]
        if consulting_role.location:
            header_parts[0] += f", {consulting_role.location}"
        if consulting_role.date_range:
            header_parts.append(consulting_role.date_range)
        header = " | ".join(header_parts)
        segments.append(_Segment(header, "role_header"))
        if consulting_role.title:
            segments.append(_Segment(consulting_role.title, "role_title"))
        for bullet in consulting_role.bullets:
            if bullet:
                segments.append(_Segment(f"• {bullet}", "bullet"))

    # Education
    education = profile.get("education", {})
    if education:
        segments.append(_Segment("", "blank"))
        segments.append(_Segment("EDUCATION", "section_header"))

        degree = education.get("degree", "")
        school = education.get("school", "")
        school_loc = education.get("location", "")
        grad = education.get("graduation", "")
        # "Degree | School, Location | Graduation"
        degree_parts = [degree]
        school_str = f"{school}, {school_loc}" if school_loc else school
        if school_str:
            degree_parts.append(school_str)
        if grad:
            degree_parts.append(grad)
        segments.append(_Segment(" | ".join(degree_parts), "edu_degree"))

        details = education.get("details", "")
        if details:
            segments.append(_Segment(details, "edu_details"))

    # Skills
    if resolved_skills:
        segments.append(_Segment("", "blank"))
        segments.append(_Segment("SKILLS", "section_header"))
        for display_name, skill_list in resolved_skills.items():
            skills_str = ", ".join(skill_list)
            # Add colon if display name doesn't already have one
            label = display_name if display_name.endswith(":") else f"{display_name}:"
            line = f"{label} {skills_str}"
            segments.append(_Segment(line, "skills_line", bold_prefix_len=len(label)))

    return segments


def _segments_to_text_and_requests(
    segments: list[_Segment],
) -> tuple[str, list[dict]]:
    """Convert segments to insertable text and formatting requests.

    Args:
        segments: Ordered list of _Segment objects

    Returns:
        Tuple of (full_text, formatting_requests)
    """
    # Build full text
    lines = [seg.text for seg in segments]
    full_text = "\n".join(lines)
    text_len = len(full_text)

    requests: list[dict] = []

    # Document-wide styles
    # Page margins: 0.6in = 43.2pt
    requests.append({
        "updateDocumentStyle": {
            "documentStyle": {
                "marginTop": {"magnitude": 43.2, "unit": "PT"},
                "marginBottom": {"magnitude": 43.2, "unit": "PT"},
                "marginLeft": {"magnitude": 43.2, "unit": "PT"},
                "marginRight": {"magnitude": 43.2, "unit": "PT"},
            },
            "fields": "marginTop,marginBottom,marginLeft,marginRight",
        }
    })

    # Default font for entire body: Garamond 10.5pt
    requests.append({
        "updateTextStyle": {
            "range": {"startIndex": 1, "endIndex": 1 + text_len},
            "textStyle": {
                "weightedFontFamily": {"fontFamily": "Garamond"},
                "fontSize": {"magnitude": 10.5, "unit": "PT"},
            },
            "fields": "weightedFontFamily,fontSize",
        }
    })

    # Default line spacing: 1.15
    requests.append({
        "updateParagraphStyle": {
            "range": {"startIndex": 1, "endIndex": 1 + text_len},
            "paragraphStyle": {
                "lineSpacing": 115,
                "spaceAbove": {"magnitude": 0, "unit": "PT"},
                "spaceBelow": {"magnitude": 0, "unit": "PT"},
            },
            "fields": "lineSpacing,spaceAbove,spaceBelow",
        }
    })

    # Per-segment formatting
    offset = 1  # Google Docs body starts at index 1

    for seg in segments:
        seg_start = offset
        seg_end = offset + len(seg.text)
        # Account for the newline after this segment
        next_offset = seg_end + 1  # +1 for \n

        if seg.kind == "name":
            requests.append({
                "updateTextStyle": {
                    "range": {"startIndex": seg_start, "endIndex": seg_end},
                    "textStyle": {
                        "bold": True,
                        "fontSize": {"magnitude": 16, "unit": "PT"},
                    },
                    "fields": "bold,fontSize",
                }
            })
            requests.append({
                "updateParagraphStyle": {
                    "range": {"startIndex": seg_start, "endIndex": seg_end},
                    "paragraphStyle": {
                        "alignment": "CENTER",
                        "spaceBelow": {"magnitude": 2, "unit": "PT"},
                    },
                    "fields": "alignment,spaceBelow",
                }
            })

        elif seg.kind == "contact":
            requests.append({
                "updateTextStyle": {
                    "range": {"startIndex": seg_start, "endIndex": seg_end},
                    "textStyle": {
                        "fontSize": {"magnitude": 9.5, "unit": "PT"},
                    },
                    "fields": "fontSize",
                }
            })
            requests.append({
                "updateParagraphStyle": {
                    "range": {"startIndex": seg_start, "endIndex": seg_end},
                    "paragraphStyle": {"alignment": "CENTER"},
                    "fields": "alignment",
                }
            })

        elif seg.kind == "links":
            requests.append({
                "updateTextStyle": {
                    "range": {"startIndex": seg_start, "endIndex": seg_end},
                    "textStyle": {
                        "fontSize": {"magnitude": 9.5, "unit": "PT"},
                    },
                    "fields": "fontSize",
                }
            })
            requests.append({
                "updateParagraphStyle": {
                    "range": {"startIndex": seg_start, "endIndex": seg_end},
                    "paragraphStyle": {"alignment": "CENTER"},
                    "fields": "alignment",
                }
            })

        elif seg.kind == "section_header":
            requests.append({
                "updateTextStyle": {
                    "range": {"startIndex": seg_start, "endIndex": seg_end},
                    "textStyle": {"bold": True},
                    "fields": "bold",
                }
            })
            requests.append({
                "updateParagraphStyle": {
                    "range": {"startIndex": seg_start, "endIndex": seg_end},
                    "paragraphStyle": {
                        "spaceAbove": {"magnitude": 6, "unit": "PT"},
                        "spaceBelow": {"magnitude": 2, "unit": "PT"},
                        "borderBottom": {
                            "color": {"color": {"rgbColor": {"red": 0, "green": 0, "blue": 0}}},
                            "width": {"magnitude": 0.5, "unit": "PT"},
                            "padding": {"magnitude": 1, "unit": "PT"},
                            "dashStyle": "SOLID",
                        },
                    },
                    "fields": "spaceAbove,spaceBelow,borderBottom",
                }
            })

        elif seg.kind == "role_header":
            requests.append({
                "updateTextStyle": {
                    "range": {"startIndex": seg_start, "endIndex": seg_end},
                    "textStyle": {"bold": True},
                    "fields": "bold",
                }
            })
            requests.append({
                "updateParagraphStyle": {
                    "range": {"startIndex": seg_start, "endIndex": seg_end},
                    "paragraphStyle": {
                        "spaceAbove": {"magnitude": 4, "unit": "PT"},
                    },
                    "fields": "spaceAbove",
                }
            })

        elif seg.kind == "role_title":
            requests.append({
                "updateTextStyle": {
                    "range": {"startIndex": seg_start, "endIndex": seg_end},
                    "textStyle": {
                        "italic": True,
                    },
                    "fields": "italic",
                }
            })

        elif seg.kind == "bullet":
            # Hanging indent: first line at 0, body at 14.4pt (0.2in)
            requests.append({
                "updateParagraphStyle": {
                    "range": {"startIndex": seg_start, "endIndex": seg_end},
                    "paragraphStyle": {
                        "indentFirstLine": {"magnitude": 0, "unit": "PT"},
                        "indentStart": {"magnitude": 14.4, "unit": "PT"},
                    },
                    "fields": "indentFirstLine,indentStart",
                }
            })

        elif seg.kind == "summary":
            pass  # Uses default font

        elif seg.kind == "edu_degree":
            requests.append({
                "updateTextStyle": {
                    "range": {"startIndex": seg_start, "endIndex": seg_end},
                    "textStyle": {"bold": True},
                    "fields": "bold",
                }
            })

        elif seg.kind == "edu_details":
            requests.append({
                "updateTextStyle": {
                    "range": {"startIndex": seg_start, "endIndex": seg_end},
                    "textStyle": {
                        "fontSize": {"magnitude": 10, "unit": "PT"},
                    },
                    "fields": "fontSize",
                }
            })

        elif seg.kind == "skills_line":
            # Bold just the category name prefix
            if seg.bold_prefix_len > 0:
                requests.append({
                    "updateTextStyle": {
                        "range": {
                            "startIndex": seg_start,
                            "endIndex": seg_start + seg.bold_prefix_len,
                        },
                        "textStyle": {"bold": True},
                        "fields": "bold",
                    }
                })

        offset = next_offset

    return full_text, requests


def generate_resume_programmatic(
    company: str,
    position: str,
    variant: str = "general",
    custom_summary: Optional[str] = None,
    skill_categories: Optional[list[str]] = None,
    custom_skills: Optional[dict[str, list[str]]] = None,
    role_bullets: Optional[dict[str, list[str]]] = None,
    max_roles: int = 5,
    max_bullets_per_role: int = 6,
    jd_text: Optional[str] = None,
    output_dir: Optional[Path] = None,
    auto_open: bool = True,
    keep_google_doc: bool = True,
) -> ResumeGenerationResult:
    """Generate an ATS-friendly resume programmatically (no template).

    Builds the entire Google Doc from scratch using insertText + formatting
    API calls. Produces a clean single-column document with no section breaks,
    tables, or multi-column layouts that break ATS parsing.

    When jd_text is provided, bullets are ranked by relevance to the job
    description using keyword matching against bullet text and tags.

    Args:
        company: Target company name
        position: Target position title
        variant: Summary variant to use (e.g., "growth", "ai-agentic")
        custom_summary: Custom summary text (overrides variant summary)
        skill_categories: Ordered list of skill category keys to include
        custom_skills: Custom skills dict (display name -> skill list)
        role_bullets: Custom bullet selection per role (company -> bullet texts)
        max_roles: Maximum number of roles to include
        max_bullets_per_role: Maximum bullets per role
        jd_text: Optional job description text for relevance-based bullet ranking
        output_dir: Directory for PDF output
        auto_open: Whether to open the PDF after generation
        keep_google_doc: Whether to keep the Google Doc

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

    config = get_gdocs_config()

    if output_dir is None:
        output_dir_str = config.get("pdf_output_dir", "~/Documents/Resumes")
        output_dir = Path(output_dir_str).expanduser()

    # Assemble data from corpus (with JD-aware bullet ranking if provided)
    try:
        data = assemble_template_data(
            variant=variant,
            max_roles=max_roles,
            max_bullets_per_role=max_bullets_per_role,
            jd_text=jd_text,
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

    # Override summary
    if custom_summary:
        data.summary = custom_summary

    # Resolve skills (limit to 5 categories)
    max_skill_categories = 5
    resolved_skills: dict[str, list[str]] = {}

    def _format_category_name(cat_key: str) -> str:
        """Format a skill category key into a display name."""
        name = cat_key.replace("-", " ").replace("_", " ").title()
        # Fix common acronym casing
        for acronym in ["Ai", "Api", "Ehr", "Cdp", "Sql", "Iam", "Sso"]:
            name = name.replace(acronym, acronym.upper())
        return name

    if custom_skills:
        resolved_skills = dict(list(custom_skills.items())[:max_skill_categories])
    elif skill_categories:
        for cat in skill_categories[:max_skill_categories]:
            if cat in data.skills_by_category:
                resolved_skills[_format_category_name(cat)] = data.skills_by_category[cat]
    else:
        for cat, skills in list(data.skills_by_category.items())[:max_skill_categories]:
            if skills:
                resolved_skills[_format_category_name(cat)] = skills

    # Determine consulting visibility
    consulting_companies = {"AI Health-Tech Startup", "Clearhead / Accenture Interactive"}
    consulting_in_main_body = any(
        r.company in consulting_companies for r in data.roles[:5]
    )
    show_consulting = (
        len(data.roles) >= 6
        and not consulting_in_main_body
        and data.roles[5].company in consulting_companies
    )

    # Build document segments
    segments = _build_resume_segments(data, resolved_skills, show_consulting)

    # Convert to text + formatting requests
    full_text, formatting_requests = _segments_to_text_and_requests(segments)

    # Build document title and PDF path
    name_data = data.profile.get("name", {})
    full_name = f"{name_data.get('first', '')} {name_data.get('last', '')}".strip() or "Resume"
    timestamp = datetime.now().strftime("%Y%m%d")
    doc_title = f"{full_name} - {position} - {company} - {timestamp}"
    pdf_filename = f"{full_name} - {position} - {company} - Resume.pdf"
    pdf_path = output_dir / pdf_filename

    try:
        client = GoogleDocsClient()
        client.authenticate()

        # Create blank document
        doc_id = client.create_document(doc_title)
        doc_url = client.get_document_url(doc_id)

        # Insert all text at once
        client.insert_text(doc_id, full_text)

        # Apply all formatting in one batch
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
        resume_id = create_resume(
            filename=pdf_path.name,
            filepath=str(pdf_path),
            variant=variant,
            summary_text=data.summary,
            target_company=company,
            target_role=position,
            google_doc_id=doc_id if keep_google_doc else None,
        )

        for role in data.roles:
            for position_idx, entry_id in enumerate(role.entry_ids):
                create_resume_entry(
                    resume_id=resume_id,
                    entry_id=entry_id,
                    role_id=role.role_id,
                    position=position_idx,
                )
                increment_entry_usage(entry_id)

        create_resume_section(
            resume_id=resume_id,
            section_type="summary",
            section_name=variant,
            content=data.summary,
        )

        for category, skills in data.skills_by_category.items():
            if skills:
                create_resume_section(
                    resume_id=resume_id,
                    section_type="skills",
                    section_name=category,
                    content=", ".join(skills),
                )

        if auto_open and pdf_path.exists():
            open_file(pdf_path)

        return ResumeGenerationResult(
            success=True,
            doc_id=final_doc_id,
            doc_url=final_doc_url,
            pdf_path=pdf_path,
            replacements_made=len(segments),
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
                try:
                    creds.refresh(Request())
                except Exception:
                    # Token revoked or expired beyond refresh — delete stale
                    # token and fall through to browser OAuth flow
                    if GDOCS_TOKEN_PATH.exists():
                        GDOCS_TOKEN_PATH.unlink()
                    creds = None

            if not creds or not creds.valid:
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

        When roles are unused or have fewer bullets than template slots,
        replacing placeholders with empty strings leaves behind commas,
        empty bullets, blank lines, and orphaned text. This method uses
        multiple passes to reliably delete those artifacts.

        Args:
            doc_id: The document ID to clean up

        Returns:
            Number of paragraphs deleted
        """
        self._ensure_authenticated()

        total_deleted = 0
        for _ in range(5):  # Up to 5 passes — each re-reads fresh indices
            deleted = self._cleanup_pass(doc_id)
            total_deleted += deleted
            if deleted == 0:
                break

        return total_deleted

    def _is_artifact_paragraph(self, text: str, is_list_item: bool) -> bool:
        """Determine if a paragraph is an artifact from empty template slots.

        Args:
            text: The raw text content of the paragraph
            is_list_item: Whether the paragraph has bullet/list formatting

        Returns:
            True if this paragraph should be deleted
        """
        stripped = text.strip()

        # Empty bullet list items (from empty {{BULLET_N}} placeholders)
        if stripped == "" and is_list_item:
            return True

        # Comma-only or comma+space lines (from empty "{{COMPANY}}, {{LOCATION}}")
        if stripped.replace(" ", "") == ",":
            return True

        # Lines that are just commas and spaces (e.g., ", " or " ,  ")
        if stripped and all(c in ", " for c in stripped):
            return True

        return False

    def _cleanup_pass(self, doc_id: str) -> int:
        """Single pass: read doc, find artifacts, delete them.

        Each pass re-reads the document so indices are fresh after
        any prior deletions. Detects both explicit artifacts (empty bullets,
        comma lines) and consecutive empty paragraphs from unused role slots.

        Returns:
            Number of paragraphs deleted in this pass
        """
        doc = self.docs_service.documents().get(documentId=doc_id).execute()
        body = doc.get("body", {})
        content = body.get("content", [])

        if not content:
            return 0

        body_end = content[-1]["endIndex"]

        # First pass: identify all paragraph info
        para_info = []  # (element, text_stripped, is_list_item, is_artifact)
        for element in content:
            if "paragraph" not in element:
                continue

            para = element["paragraph"]
            text = ""
            for elem in para.get("elements", []):
                text += elem.get("textRun", {}).get("content", "")

            stripped = text.strip()
            is_list_item = "bullet" in para
            is_artifact = self._is_artifact_paragraph(text, is_list_item)
            para_info.append((element, stripped, is_list_item, is_artifact))

        # Second pass: also mark consecutive empty non-list paragraphs as artifacts.
        # A single blank line between roles is intentional spacing; 2+ consecutive
        # blank lines are artifacts from empty role headers (title, dates).
        for i in range(len(para_info)):
            element, stripped, is_list_item, is_artifact = para_info[i]
            if is_artifact or stripped:
                continue
            # This is a non-artifact empty paragraph. Check if it's adjacent
            # to another empty paragraph (artifact or not).
            has_empty_neighbor = False
            if i > 0:
                _, prev_stripped, _, prev_artifact = para_info[i - 1]
                if prev_stripped == "" or prev_artifact:
                    has_empty_neighbor = True
            if i < len(para_info) - 1:
                _, next_stripped, _, next_artifact = para_info[i + 1]
                if next_stripped == "" or next_artifact:
                    has_empty_neighbor = True
            if has_empty_neighbor:
                para_info[i] = (element, stripped, is_list_item, True)

        # Collect ranges to delete
        delete_ranges = []
        for element, stripped, is_list_item, is_artifact in para_info:
            if not is_artifact:
                continue
            start = element["startIndex"]
            end = element["endIndex"]
            # Don't delete the doc body start (index 0-1)
            if start < 2:
                continue
            # Can't delete the body's final newline — shrink range
            if end >= body_end:
                end = body_end - 1
                if end <= start:
                    continue
            delete_ranges.append((start, end))

        if not delete_ranges:
            return 0

        # Delete in reverse order so earlier indices aren't affected
        delete_ranges.sort(key=lambda r: r[0], reverse=True)

        # Delete one at a time in reverse — each deletion is independent
        # because we only affect content after the current range
        deleted = 0
        for start, end in delete_ranges:
            try:
                self.docs_service.documents().batchUpdate(
                    documentId=doc_id,
                    body={"requests": [{
                        "deleteContentRange": {
                            "range": {
                                "startIndex": start,
                                "endIndex": end,
                            }
                        }
                    }]},
                ).execute()
                deleted += 1
            except Exception:
                # Range may span a structural boundary (table cell, etc.)
                # Skip it — a subsequent pass with fresh indices may catch it
                pass

        return deleted

    def flatten_column_sections(self, doc_id: str) -> int:
        """Convert all multi-column sections to single-column.

        Resume templates often use 2-column section breaks for role headers
        (company on left, dates on right). ATS systems and PDF copy-paste
        can't handle multi-column sections — dates get disassociated from
        role titles and phantom empty bullets appear.

        Uses updateSectionStyle to convert each 2-column section to
        single-column while preserving the content.

        Args:
            doc_id: The document ID to modify

        Returns:
            Number of column sections flattened
        """
        self._ensure_authenticated()

        doc = self.docs_service.documents().get(documentId=doc_id).execute()
        body = doc.get("body", {})
        content = body.get("content", [])

        flattened = 0
        for i, element in enumerate(content):
            if "sectionBreak" not in element:
                continue
            style = element["sectionBreak"].get("sectionStyle", {})
            cols = style.get("columnProperties", [])
            if len(cols) < 2:
                continue

            # Find the first paragraph in this section to use as the range
            para_start = None
            para_end = None
            for j in range(i + 1, len(content)):
                if "paragraph" in content[j]:
                    para_start = content[j]["startIndex"]
                    para_end = content[j]["endIndex"]
                    break
                elif "sectionBreak" in content[j]:
                    break

            if para_start is None:
                continue

            try:
                self.docs_service.documents().batchUpdate(
                    documentId=doc_id,
                    body={"requests": [{
                        "updateSectionStyle": {
                            "range": {
                                "startIndex": para_start,
                                "endIndex": para_end,
                            },
                            "sectionStyle": {
                                "columnProperties": [{}],
                            },
                            "fields": "columnProperties",
                        }
                    }]},
                ).execute()
                flattened += 1
            except Exception:
                pass

        return flattened

    def flatten_tables(self, doc_id: str) -> int:
        """Convert table-based layouts to simple paragraphs for ATS compatibility.

        Resume templates often use tables for side-by-side layout (e.g.,
        company name on left, dates on right). ATS systems can't parse tables
        reliably, causing dates to be disassociated from role titles.

        This method finds tables, extracts text from each row (joining cells
        with tab characters), replaces each table with plain paragraphs, and
        copies basic formatting (bold, font size) from the original cells.

        Args:
            doc_id: The document ID to modify

        Returns:
            Number of tables flattened
        """
        self._ensure_authenticated()

        doc = self.docs_service.documents().get(documentId=doc_id).execute()
        body = doc.get("body", {})
        content = body.get("content", [])

        # Find all tables
        tables = []
        for element in content:
            if "table" in element:
                tables.append(element)

        if not tables:
            return 0

        # Process tables in reverse order (so indices don't shift)
        tables.sort(key=lambda t: t["startIndex"], reverse=True)
        flattened = 0

        for table_element in tables:
            table = table_element["table"]
            table_start = table_element["startIndex"]
            table_end = table_element["endIndex"]

            # Extract text from each row, joining cells with tab
            row_texts = []
            row_styles = []
            for row in table.get("tableRows", []):
                cell_texts = []
                first_style = {}
                for cell_idx, cell in enumerate(row.get("tableCells", [])):
                    cell_text = ""
                    for cell_content in cell.get("content", []):
                        if "paragraph" in cell_content:
                            for elem in cell_content["paragraph"].get("elements", []):
                                text_run = elem.get("textRun", {})
                                cell_text += text_run.get("content", "")
                                # Capture formatting from first non-empty cell
                                if cell_idx == 0 and not first_style:
                                    first_style = text_run.get("textStyle", {})
                    cell_texts.append(cell_text.strip())
                # Filter empty cells, join with tab for right-alignment effect
                non_empty = [t for t in cell_texts if t]
                row_text = "\t".join(non_empty)
                row_texts.append(row_text)
                row_styles.append(first_style)

            # Build requests: delete table, insert replacement text
            requests = []

            # Delete the table
            requests.append({
                "deleteContentRange": {
                    "range": {
                        "startIndex": table_start,
                        "endIndex": table_end,
                    }
                }
            })

            # Insert replacement text at the table's start position
            # Insert in reverse order so each goes to the same position
            for row_text in reversed(row_texts):
                if row_text:  # Skip fully empty rows
                    requests.append({
                        "insertText": {
                            "location": {"index": table_start},
                            "text": row_text + "\n",
                        }
                    })

            try:
                self.docs_service.documents().batchUpdate(
                    documentId=doc_id,
                    body={"requests": requests},
                ).execute()
                flattened += 1
            except Exception:
                pass  # Skip tables that can't be flattened

        return flattened

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
