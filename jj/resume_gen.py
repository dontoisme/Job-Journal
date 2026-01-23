"""Resume generator using docx template with exact formatting preservation.

Uses direct XML text replacement to swap content while keeping all styles,
tables, borders, and layout intact.

Extended with:
- Corpus-aware entry selection
- Validation that all bullets come from corpus
- Gap analysis and improvement suggestions
- Full resume/entry tracking in database
"""

import json
import re
import shutil
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
import tempfile


# Default template path
DEFAULT_TEMPLATE = Path.home() / ".job-journal" / "templates" / "_Don Hogan - Principal Product Manager - Resume.docx"
OUTPUT_DIR = Path.home() / "Documents" / "Resumes"


@dataclass
class ResumeGenerationResult:
    """Result of a resume generation operation."""

    resume_id: Optional[int] = None
    filepath: Optional[Path] = None
    filename: str = ""
    variant: Optional[str] = None
    entries_used: int = 0
    sections_created: int = 0
    drift_score: int = 0
    is_valid: bool = True
    suggestions: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class SelectedEntry:
    """An entry selected for inclusion in a resume."""

    entry_id: int
    role_id: int
    text: str
    category: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    position: int = 0


def replace_text_in_xml(xml_content: str, replacements: dict[str, str]) -> str:
    """Replace text in docx XML while preserving formatting.

    Args:
        xml_content: The document.xml content
        replacements: Dict mapping old text -> new text

    Returns:
        Modified XML content
    """
    for old_text, new_text in replacements.items():
        # Escape special XML characters in both old and new text for matching
        old_text_escaped = (
            old_text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        new_text_escaped = (
            new_text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        # Simple string replacement - works because text is within tags
        xml_content = xml_content.replace(old_text_escaped, new_text_escaped)
        # Also try without escaping (for text that doesn't have special chars)
        if old_text != old_text_escaped:
            xml_content = xml_content.replace(old_text, new_text_escaped)

    return xml_content


def generate_resume(
    replacements: dict[str, str],
    template_path: Optional[Path] = None,
    output_name: Optional[str] = None,
    company: str = "Company",
    position: str = "Role"
) -> Path:
    """Generate a resume by replacing text in template.

    Args:
        replacements: Dict mapping template text -> new text
        template_path: Path to template docx (uses default if None)
        output_name: Custom output filename (auto-generated if None)
        company: Company name for default filename
        position: Position for default filename

    Returns:
        Path to generated resume
    """
    template = template_path or DEFAULT_TEMPLATE

    if not template.exists():
        raise FileNotFoundError(f"Template not found: {template}")

    # Create output filename
    if output_name:
        output_path = OUTPUT_DIR / output_name
    else:
        output_path = OUTPUT_DIR / f"Don Hogan - {position} - {company} - Resume.docx"

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Work in temp directory
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Extract template
        with zipfile.ZipFile(template, 'r') as zf:
            zf.extractall(tmpdir)

        # Read and modify document.xml
        doc_xml_path = tmpdir / "word" / "document.xml"
        with open(doc_xml_path, 'r', encoding='utf-8') as f:
            xml_content = f.read()

        # Apply replacements
        xml_content = replace_text_in_xml(xml_content, replacements)

        # Write modified XML
        with open(doc_xml_path, 'w', encoding='utf-8') as f:
            f.write(xml_content)

        # Repack docx
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for file_path in tmpdir.rglob('*'):
                if file_path.is_file():
                    arcname = file_path.relative_to(tmpdir)
                    zf.write(file_path, arcname)

    return output_path


# =============================================================================
# Corpus-Aware Resume Generation
# =============================================================================

def select_entries_for_variant(
    variant: str,
    max_per_role: int = 4,
    prioritize_used: bool = True,
) -> list[SelectedEntry]:
    """
    Select corpus entries appropriate for a resume variant.

    Args:
        variant: Resume variant (growth, ai-agentic, health-tech, etc.)
        max_per_role: Maximum bullets per role
        prioritize_used: Whether to prioritize frequently used entries

    Returns:
        List of SelectedEntry objects
    """
    from jj.corpus import get_entries_by_variant
    from jj.db import get_roles, get_entries_for_role

    entries = get_entries_by_variant(variant)
    roles = get_roles()

    selected = []
    position = 0

    for role in roles:
        # Get entries for this role matching the variant
        role_entries = [e for e in entries if e.get("role_id") == role["id"]]

        # Sort by times_used (most used first) if prioritizing
        if prioritize_used:
            role_entries.sort(key=lambda e: e.get("times_used", 0), reverse=True)

        # Select top N entries for this role
        for entry in role_entries[:max_per_role]:
            tags = entry.get("tags") or "[]"
            if isinstance(tags, str):
                try:
                    tags = json.loads(tags)
                except:
                    tags = []

            selected.append(SelectedEntry(
                entry_id=entry["id"],
                role_id=role["id"],
                text=entry["text"],
                category=entry.get("category"),
                tags=tags,
                position=position,
            ))
            position += 1

    return selected


def validate_resume_content(
    bullets: list[str],
    fail_fast: bool = True,
) -> tuple[bool, int, list[dict[str, Any]]]:
    """
    Validate that all resume bullets exist in the corpus.

    Args:
        bullets: List of bullet texts to validate
        fail_fast: If True, raise exception on first invalid bullet

    Returns:
        Tuple of (is_valid, drift_score, validation_results)
    """
    from jj.corpus import validate_bullets

    results = validate_bullets(bullets)

    if fail_fast and results["invalid"] > 0:
        invalid_bullets = [r["bullet"] for r in results["results"] if not r["valid"]]
        raise ValueError(
            f"Resume validation failed: {results['invalid']} bullets not found in corpus.\n"
            f"Invalid bullets: {invalid_bullets[:3]}..."
        )

    return (
        results["invalid"] == 0,
        results["drift_score"],
        results["results"],
    )


def analyze_jd_gaps(
    jd_keywords: list[str],
    jd_themes: list[str],
    selected_entries: list[SelectedEntry],
    variant: str,
) -> list[dict[str, Any]]:
    """
    Analyze gaps between JD requirements and selected corpus entries.

    Args:
        jd_keywords: Keywords extracted from job description
        jd_themes: Themes/requirements from job description
        selected_entries: Entries selected for the resume
        variant: Resume variant

    Returns:
        List of gap suggestions
    """
    from jj.db import get_roles

    suggestions = []
    roles = get_roles()

    # Collect all tags from selected entries
    selected_tags = set()
    selected_text_lower = ""
    for entry in selected_entries:
        selected_tags.update(entry.tags)
        selected_text_lower += " " + entry.text.lower()

    # Check each JD keyword/theme for coverage
    for keyword in jd_keywords:
        keyword_lower = keyword.lower()
        if keyword_lower not in selected_text_lower:
            # Not covered - create suggestion
            suggestions.append({
                "gap_type": "missing_keyword",
                "theme": keyword,
                "suggestion": f"JD mentions '{keyword}' but no corpus bullets contain this term. "
                             f"Consider adding a bullet about {keyword} to your experience.",
            })

    for theme in jd_themes:
        theme_lower = theme.lower()
        # Check if any tag matches
        if not any(theme_lower in tag.lower() for tag in selected_tags):
            if theme_lower not in selected_text_lower:
                # Suggest which role might be best to add this to
                suggested_role = roles[0] if roles else None

                suggestions.append({
                    "gap_type": "missing_theme",
                    "theme": theme,
                    "suggested_role_id": suggested_role["id"] if suggested_role else None,
                    "suggestion": f"JD emphasizes '{theme}' but corpus coverage is weak. "
                                 f"Consider adding bullets demonstrating {theme}.",
                })

    return suggestions


def generate_resume_with_tracking(
    replacements: dict[str, str],
    selected_entries: list[SelectedEntry],
    variant: Optional[str] = None,
    summary_text: Optional[str] = None,
    target_company: str = "Company",
    target_role: str = "Role",
    jd_url: Optional[str] = None,
    jd_keywords: Optional[list[str]] = None,
    jd_themes: Optional[list[str]] = None,
    template_path: Optional[Path] = None,
    output_name: Optional[str] = None,
    validate: bool = True,
    create_suggestions: bool = True,
) -> ResumeGenerationResult:
    """
    Generate a resume with full corpus tracking.

    This is the main entry point for corpus-aware resume generation.

    Args:
        replacements: Text replacements for the template
        selected_entries: Corpus entries to include
        variant: Resume variant
        summary_text: The composed summary paragraph
        target_company: Target company name
        target_role: Target role/position
        jd_url: URL of job description
        jd_keywords: Keywords from JD (for gap analysis)
        jd_themes: Themes from JD (for gap analysis)
        template_path: Path to template docx
        output_name: Custom output filename
        validate: Whether to validate bullets against corpus
        create_suggestions: Whether to create gap suggestions

    Returns:
        ResumeGenerationResult with all tracking info
    """
    from jj.db import (
        create_resume,
        create_resume_entry,
        create_resume_section,
        create_corpus_suggestion,
        increment_entry_usage,
        validate_resume,
    )

    result = ResumeGenerationResult(variant=variant)

    # Validate bullets if requested
    if validate and selected_entries:
        bullets = [e.text for e in selected_entries]
        try:
            is_valid, drift_score, _ = validate_resume_content(bullets, fail_fast=True)
            result.is_valid = is_valid
            result.drift_score = drift_score
        except ValueError as e:
            result.errors.append(str(e))
            result.is_valid = False
            return result

    # Generate the resume file
    try:
        output_path = generate_resume(
            replacements=replacements,
            template_path=template_path,
            output_name=output_name,
            company=target_company,
            position=target_role,
        )
        result.filepath = output_path
        result.filename = output_path.name
    except Exception as e:
        result.errors.append(f"Resume generation failed: {e}")
        return result

    # Create database record
    resume_id = create_resume(
        filename=output_path.name,
        filepath=str(output_path),
        variant=variant,
        summary_text=summary_text,
        target_company=target_company,
        target_role=target_role,
        jd_url=jd_url,
        drift_score=result.drift_score,
        is_valid=result.is_valid,
    )
    result.resume_id = resume_id

    # Link entries to resume
    for entry in selected_entries:
        create_resume_entry(
            resume_id=resume_id,
            entry_id=entry.entry_id,
            role_id=entry.role_id,
            position=entry.position,
        )
        # Increment usage counter
        increment_entry_usage(entry.entry_id)
        result.entries_used += 1

    # Create sections tracking
    if summary_text:
        create_resume_section(
            resume_id=resume_id,
            section_type="summary",
            content=summary_text,
            position=0,
        )
        result.sections_created += 1

    # Analyze gaps and create suggestions
    if create_suggestions and (jd_keywords or jd_themes):
        suggestions = analyze_jd_gaps(
            jd_keywords=jd_keywords or [],
            jd_themes=jd_themes or [],
            selected_entries=selected_entries,
            variant=variant or "general",
        )

        for suggestion in suggestions:
            create_corpus_suggestion(
                gap_type=suggestion["gap_type"],
                theme=suggestion["theme"],
                suggestion=suggestion["suggestion"],
                resume_id=resume_id,
                jd_url=jd_url,
                suggested_role_id=suggestion.get("suggested_role_id"),
            )
            result.suggestions.append(suggestion)

    # Mark as validated
    validate_resume(resume_id, result.is_valid, result.drift_score)

    return result


def list_resumes(
    variant: Optional[str] = None,
    company: Optional[str] = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """List generated resumes with their entry counts."""
    from jj.db import get_resumes, get_resume_entries

    resumes = get_resumes(variant=variant, company=company, limit=limit)

    # Enrich with entry counts
    for resume in resumes:
        entries = get_resume_entries(resume["id"])
        resume["entry_count"] = len(entries)

    return resumes


def get_resume_details(resume_id: int) -> Optional[dict[str, Any]]:
    """Get full details of a resume including entries and sections."""
    from jj.db import get_resume, get_resume_entries, get_resume_sections

    resume = get_resume(resume_id)
    if not resume:
        return None

    resume["entries"] = get_resume_entries(resume_id)
    resume["sections"] = get_resume_sections(resume_id)

    return resume


def revalidate_resume(resume_id: int) -> dict[str, Any]:
    """Re-validate an existing resume against current corpus."""
    from jj.db import get_resume_entries, validate_resume

    entries = get_resume_entries(resume_id)
    bullets = [e["text"] for e in entries]

    is_valid, drift_score, results = validate_resume_content(bullets, fail_fast=False)

    validate_resume(resume_id, is_valid, drift_score)

    return {
        "resume_id": resume_id,
        "is_valid": is_valid,
        "drift_score": drift_score,
        "total_bullets": len(bullets),
        "invalid_bullets": [r for r in results if not r["valid"]],
    }


# Example usage / quick test
if __name__ == "__main__":
    # Test with a simple replacement
    test_replacements = {
        "Growth and activation specialist": "TEST REPLACEMENT specialist",
    }

    output = generate_resume(
        replacements=test_replacements,
        company="TestCo",
        position="Test Role"
    )
    print(f"Generated: {output}")
