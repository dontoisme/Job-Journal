"""Parser for base.md format and corpus generation."""

import re
from pathlib import Path
from typing import Any, Optional

from jj.config import CORPUS_PATH, get_full_name, load_profile
from jj.db import (
    create_entry,
    create_role,
    create_skill,
    find_role_by_company_title,
    get_entries_for_role,
    get_roles,
    get_skills,
)

# Metric extraction patterns
METRIC_PATTERNS = [
    r'\d+%',                    # Percentages
    r'\$[\d,]+[KMB]?',          # Dollar amounts
    r'\d+x',                    # Multipliers
    r'\d{2,}[,\d]*',            # Large numbers
    r'\d+-\d+%',                # Percentage ranges
]


def extract_metrics(text: str) -> list[str]:
    """Extract metrics from bullet text."""
    metrics = []
    for pattern in METRIC_PATTERNS:
        matches = re.findall(pattern, text, re.IGNORECASE)
        metrics.extend(matches)
    return list(set(metrics))


def extract_tags(text: str, category: Optional[str] = None) -> list[str]:
    """Extract tags from bullet text based on keywords."""
    tags = []
    text_lower = text.lower()

    # Tag mappings
    tag_keywords = {
        "ai": ["ai", "artificial intelligence", "machine learning", "ml", "llm"],
        "agentic": ["agent", "agentic", "autonomous", "orchestration"],
        "growth": ["growth", "activation", "retention", "funnel", "conversion"],
        "experimentation": ["a/b test", "experiment", "testing"],
        "analytics": ["analytics", "metrics", "data", "dashboard", "sql"],
        "api": ["api", "integration", "endpoint"],
        "health-tech": ["health", "clinical", "patient", "ehr", "pharmacy"],
        "leadership": ["led", "managed", "founded", "established", "team"],
        "platform": ["platform", "infrastructure", "architecture"],
        "mobile": ["mobile", "ios", "android", "app"],
        "web": ["web", "frontend", "backend"],
    }

    for tag, keywords in tag_keywords.items():
        if any(kw in text_lower for kw in keywords):
            tags.append(tag)

    # Add category as tag if provided
    if category and category not in tags:
        tags.append(category)

    return tags


def parse_base_md(path: Path) -> dict[str, Any]:
    """
    Parse a base.md file and extract roles, bullets, and metadata.

    Returns a dict with:
    - roles: list of role dicts
    - summaries: dict of summary templates by theme
    - skills: dict of skill categories
    """
    content = path.read_text()
    lines = content.split("\n")

    result = {
        "roles": [],
        "summaries": {},
        "skills": {},
        "approved_specifics": {},
    }

    current_section = None
    current_role = None
    current_category = None
    line_num = 0

    i = 0
    while i < len(lines):
        line = lines[i]
        line_num = i + 1

        # Detect major sections
        if line.startswith("## SUMMARY"):
            current_section = "summaries"
            current_role = None
        elif line.startswith("## SKILLS"):
            current_section = "skills"
            current_role = None
        elif line.startswith("## EXPERIENCE"):
            current_section = "experience"
            current_role = None
        elif line.startswith("## APPROVED SPECIFICS"):
            current_section = "approved"
            current_role = None
        elif line.startswith("## EDUCATION"):
            current_section = "education"
            current_role = None
        elif line.startswith("## "):
            current_section = None
            current_role = None

        # Parse roles in experience section
        elif current_section == "experience" and line.startswith("### "):
            # New role header
            title = line[4:].strip()

            # Look for company line
            i += 1
            if i < len(lines):
                company_line = lines[i]
                company_match = re.match(r'\*\*(.+?)\*\*\s*[—-]\s*(.+?)\s*\|\s*(.+)', company_line)
                if company_match:
                    company = company_match.group(1).strip()
                    location = company_match.group(2).strip()
                    dates = company_match.group(3).strip()

                    # Parse dates
                    start_date = None
                    end_date = None
                    is_current = "Present" in dates or dates.endswith(str(__import__('datetime').date.today().year))

                    current_role = {
                        "title": title,
                        "company": company,
                        "location": location,
                        "start_date": start_date,
                        "end_date": end_date,
                        "is_current": is_current,
                        "tags": [],
                        "bullets": [],
                    }
                    result["roles"].append(current_role)

        # Parse tags line
        elif current_role and line.startswith("_Tags:"):
            tags_match = re.match(r'_Tags:\s*(.+)_', line)
            if tags_match:
                current_role["tags"] = [t.strip() for t in tags_match.group(1).split(",")]

        # Parse category headers within role
        elif current_role and line.startswith("**") and line.endswith(":**"):
            current_category = line[2:-3].lower().replace(" bullets", "").replace(" ", "-")

        # Parse bullet points
        elif current_role and line.startswith("- "):
            bullet_text = line[2:].strip()
            if bullet_text:
                metrics = extract_metrics(bullet_text)
                tags = extract_tags(bullet_text, current_category)

                current_role["bullets"].append({
                    "text": bullet_text,
                    "category": current_category,
                    "tags": tags,
                    "metrics": metrics,
                    "line_number": line_num,
                })

        # Parse skills section
        elif current_section == "skills" and line.startswith("**") and ":" in line:
            # Skill category header
            cat_match = re.match(r'\*\*(.+?):\*\*', line)
            if cat_match:
                category_name = cat_match.group(1).strip()
                # Skills are on the same line or next line
                skills_text = line.split(":**")[-1].strip()
                if not skills_text:
                    i += 1
                    if i < len(lines):
                        skills_text = lines[i].strip("- ")

                if skills_text:
                    skill_list = [s.strip() for s in skills_text.split(",")]
                    result["skills"][category_name] = skill_list

        # Parse summary templates
        elif current_section == "summaries" and line.startswith("**") and line.endswith(":**"):
            theme_match = re.match(r'\*\*(.+?):\*\*', line)
            if theme_match:
                theme = theme_match.group(1).strip().lower().replace("/", "-")
                # Summary is in next blockquote
                i += 1
                summary_lines = []
                while i < len(lines) and (lines[i].startswith(">") or lines[i].strip() == ""):
                    if lines[i].startswith(">"):
                        summary_lines.append(lines[i][1:].strip())
                    i += 1
                i -= 1  # Back up one since loop will increment
                if summary_lines:
                    result["summaries"][theme] = " ".join(summary_lines)

        i += 1

    return result


def import_base_md(path: Path) -> dict[str, int]:
    """
    Import a base.md file into the database.

    Returns stats about what was imported.
    """
    parsed = parse_base_md(path)

    stats = {"roles": 0, "entries": 0, "skills": 0}

    # Import roles and entries
    for role_data in parsed["roles"]:
        # Check if role already exists
        existing = find_role_by_company_title(role_data["company"], role_data["title"])

        if existing:
            role_id = existing["id"]
        else:
            role_id = create_role(
                title=role_data["title"],
                company=role_data["company"],
                location=role_data.get("location"),
                start_date=role_data.get("start_date"),
                end_date=role_data.get("end_date"),
                is_current=role_data.get("is_current", False),
                tags=role_data.get("tags", []),
            )
            stats["roles"] += 1

        # Import bullets as entries
        for bullet in role_data.get("bullets", []):
            entry_id = create_entry(
                role_id=role_id,
                text=bullet["text"],
                category=bullet.get("category"),
                tags=bullet.get("tags", []),
                metrics=bullet.get("metrics", []),
                source="import",
                source_line=bullet.get("line_number"),
            )
            if entry_id:
                stats["entries"] += 1

    # Import skills
    for category, skill_list in parsed.get("skills", {}).items():
        for skill_name in skill_list:
            skill_id = create_skill(
                name=skill_name,
                category=category.lower().replace(" ", "-"),
            )
            if skill_id:
                stats["skills"] += 1

    # Generate corpus.md from imported data
    generate_corpus_md()

    return stats


def generate_corpus_md() -> None:
    """Generate corpus.md from database contents."""
    load_profile()
    name = get_full_name() or "Your Name"

    lines = [
        f"# {name} - Professional Corpus",
        "",
        "Generated from Job Journal. Edit freely - changes sync back to database.",
        "",
        "---",
        "",
    ]

    # Skills section
    skills = get_skills()
    if skills:
        lines.extend(["## SKILLS", ""])

        # Group by category
        by_category: dict[str, list[str]] = {}
        for skill in skills:
            cat = skill.get("category") or "general"
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(skill["name"])

        for category, skill_list in by_category.items():
            cat_title = category.replace("-", " ").title()
            lines.append(f"**{cat_title}:** {', '.join(skill_list)}")
            lines.append("")

        lines.append("---")
        lines.append("")

    # Experience section
    roles = get_roles()
    if roles:
        lines.extend(["## EXPERIENCE", ""])

        for role in roles:
            lines.append(f"### {role['title']}")
            company = role.get("company", "Unknown")
            location = role.get("location", "")
            dates = ""
            if role.get("start_date"):
                dates = role["start_date"]
                if role.get("end_date"):
                    dates += f" – {role['end_date']}"
                elif role.get("is_current"):
                    dates += " – Present"

            line_parts = [f"**{company}**"]
            if location:
                line_parts.append(f"— {location}")
            if dates:
                line_parts.append(f"| {dates}")
            lines.append(" ".join(line_parts))
            lines.append("")

            # Tags
            tags = role.get("tags")
            if tags:
                if isinstance(tags, str):
                    import json
                    try:
                        tags = json.loads(tags)
                    except (json.JSONDecodeError, TypeError):
                        tags = []
                if tags:
                    lines.append(f"_Tags: {', '.join(tags)}_")
                    lines.append("")

            # Entries for this role
            entries = get_entries_for_role(role["id"])

            # Group by category
            by_cat: dict[str, list[dict]] = {}
            for entry in entries:
                cat = entry.get("category") or "general"
                if cat not in by_cat:
                    by_cat[cat] = []
                by_cat[cat].append(entry)

            for category, cat_entries in by_cat.items():
                cat_title = category.replace("-", " ").title()
                lines.append(f"**{cat_title} bullets:**")
                for entry in cat_entries:
                    lines.append(f"- {entry['text']}")
                lines.append("")

            lines.append("---")
            lines.append("")

    # Write corpus file
    CORPUS_PATH.write_text("\n".join(lines))
