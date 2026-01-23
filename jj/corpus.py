"""Corpus management - sync base.md to database and provide matching utilities.

The corpus is the source of truth for all resume bullets. This module:
1. Parses base.md into structured entries
2. Syncs entries to the database with line-number tracking
3. Provides fuzzy matching for bullet comparison
4. Validates that resume bullets exist in corpus
"""

import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Optional

from jj.db import (
    create_entry,
    create_role,
    delete_entries_by_source,
    find_entry_by_text,
    find_role_by_company_title,
    get_all_entries,
    get_entries_for_role,
    get_role,
    get_roles,
    update_entry,
)
from jj.parser import extract_metrics, extract_tags, parse_base_md


# Default base.md location
DEFAULT_BASE_MD = Path.home() / ".job-apply" / "resume" / "base.md"


class CorpusSyncResult:
    """Result of a corpus sync operation."""

    def __init__(self):
        self.roles_added = 0
        self.roles_updated = 0
        self.entries_added = 0
        self.entries_updated = 0
        self.entries_deleted = 0
        self.errors: list[str] = []

    def __str__(self) -> str:
        return (
            f"Synced: {self.entries_added} entries added, "
            f"{self.entries_updated} updated, {self.entries_deleted} removed. "
            f"Roles: {self.roles_added} added, {self.roles_updated} updated."
        )


def sync_from_base_md(
    path: Optional[Path] = None,
    replace: bool = False,
) -> CorpusSyncResult:
    """
    Sync entries from base.md to the database.

    Args:
        path: Path to base.md file (uses default if None)
        replace: If True, delete existing base.md entries before sync

    Returns:
        CorpusSyncResult with sync statistics
    """
    base_path = path or DEFAULT_BASE_MD
    result = CorpusSyncResult()

    if not base_path.exists():
        result.errors.append(f"File not found: {base_path}")
        return result

    # Parse base.md
    try:
        parsed = parse_base_md(base_path)
    except Exception as e:
        result.errors.append(f"Parse error: {e}")
        return result

    # Optionally clear existing base.md entries
    if replace:
        result.entries_deleted = delete_entries_by_source("base.md")

    # Process roles and entries
    for role_data in parsed.get("roles", []):
        # Find or create role
        existing_role = find_role_by_company_title(
            role_data["company"], role_data["title"]
        )

        if existing_role:
            role_id = existing_role["id"]
            result.roles_updated += 1
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
            result.roles_added += 1

        # Process bullets for this role
        for bullet in role_data.get("bullets", []):
            text = bullet["text"]
            line_num = bullet.get("line_number")

            # Check if entry exists
            existing_entry = find_entry_by_text(text, exact=True)

            if existing_entry:
                # Update source_line if changed
                if existing_entry.get("source_line") != line_num:
                    update_entry(
                        existing_entry["id"],
                        source="base.md",
                        source_line=line_num,
                    )
                    result.entries_updated += 1
            else:
                # Create new entry
                create_entry(
                    role_id=role_id,
                    text=text,
                    category=bullet.get("category"),
                    tags=bullet.get("tags", []),
                    metrics=bullet.get("metrics", []),
                    source="base.md",
                    source_line=line_num,
                )
                result.entries_added += 1

    return result


def fuzzy_match_score(text1: str, text2: str) -> float:
    """
    Calculate fuzzy match score between two texts.

    Returns a score from 0.0 to 1.0 where 1.0 is an exact match.
    """
    # Normalize texts
    t1 = normalize_text(text1)
    t2 = normalize_text(text2)

    return SequenceMatcher(None, t1, t2).ratio()


def normalize_text(text: str) -> str:
    """Normalize text for comparison."""
    # Lowercase
    text = text.lower()
    # Remove extra whitespace
    text = " ".join(text.split())
    # Remove common variations
    text = text.replace("–", "-").replace("—", "-")
    text = text.replace("'", "'").replace(""", '"').replace(""", '"')
    return text


def find_matching_entry(
    bullet_text: str,
    threshold: float = 0.85,
) -> Optional[dict[str, Any]]:
    """
    Find a corpus entry that matches the given bullet text.

    Args:
        bullet_text: The bullet text to match
        threshold: Minimum similarity score (0-1) for a match

    Returns:
        Matching entry dict or None if no match found
    """
    entries = get_all_entries()

    best_match = None
    best_score = 0.0

    for entry in entries:
        score = fuzzy_match_score(bullet_text, entry["text"])
        if score > best_score:
            best_score = score
            best_match = entry

    if best_match and best_score >= threshold:
        return {**best_match, "match_score": best_score}

    return None


def find_all_matching_entries(
    bullet_text: str,
    threshold: float = 0.7,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """
    Find all corpus entries that potentially match the given bullet text.

    Args:
        bullet_text: The bullet text to match
        threshold: Minimum similarity score for inclusion
        limit: Maximum number of matches to return

    Returns:
        List of matching entries with match_score, sorted by score
    """
    entries = get_all_entries()

    matches = []
    for entry in entries:
        score = fuzzy_match_score(bullet_text, entry["text"])
        if score >= threshold:
            matches.append({**entry, "match_score": score})

    # Sort by score descending
    matches.sort(key=lambda x: x["match_score"], reverse=True)

    return matches[:limit]


def validate_bullet(bullet_text: str) -> dict[str, Any]:
    """
    Validate that a bullet exists in the corpus.

    Returns:
        dict with 'valid', 'exact_match', 'best_match', 'score'
    """
    # Check exact match first
    exact = find_entry_by_text(bullet_text, exact=True)
    if exact:
        return {
            "valid": True,
            "exact_match": True,
            "entry": exact,
            "score": 1.0,
        }

    # Try fuzzy match
    fuzzy = find_matching_entry(bullet_text, threshold=0.95)
    if fuzzy:
        return {
            "valid": True,
            "exact_match": False,
            "entry": fuzzy,
            "score": fuzzy["match_score"],
        }

    # No match - find closest for debugging
    closest = find_matching_entry(bullet_text, threshold=0.0)

    return {
        "valid": False,
        "exact_match": False,
        "closest_match": closest,
        "score": closest["match_score"] if closest else 0.0,
    }


def validate_bullets(bullets: list[str]) -> dict[str, Any]:
    """
    Validate a list of bullets against the corpus.

    Returns:
        dict with validation results and drift score
    """
    results = []
    valid_count = 0
    drift_score = 0

    for bullet in bullets:
        validation = validate_bullet(bullet)
        results.append({"bullet": bullet, **validation})

        if validation["valid"]:
            valid_count += 1
            # Small penalty for fuzzy (non-exact) matches
            if not validation["exact_match"]:
                drift_score += 1
        else:
            drift_score += 10  # Large penalty for invalid bullets

    return {
        "total": len(bullets),
        "valid": valid_count,
        "invalid": len(bullets) - valid_count,
        "drift_score": drift_score,
        "results": results,
    }


def get_corpus_stats() -> dict[str, Any]:
    """Get statistics about the corpus."""
    entries = get_all_entries()
    roles = get_roles()

    # Count by source
    by_source: dict[str, int] = {}
    for entry in entries:
        source = entry.get("source") or "unknown"
        by_source[source] = by_source.get(source, 0) + 1

    # Count by category
    by_category: dict[str, int] = {}
    for entry in entries:
        category = entry.get("category") or "uncategorized"
        by_category[category] = by_category.get(category, 0) + 1

    # Count by role
    by_role: dict[str, int] = {}
    for entry in entries:
        role_key = f"{entry.get('role_title', 'Unknown')} @ {entry.get('company', 'Unknown')}"
        by_role[role_key] = by_role.get(role_key, 0) + 1

    return {
        "total_entries": len(entries),
        "total_roles": len(roles),
        "by_source": by_source,
        "by_category": by_category,
        "by_role": by_role,
    }


def search_corpus(
    query: Optional[str] = None,
    tags: Optional[list[str]] = None,
    role_id: Optional[int] = None,
    category: Optional[str] = None,
) -> list[dict[str, Any]]:
    """
    Search the corpus with various filters.

    Args:
        query: Text search query
        tags: Filter by tags
        role_id: Filter by role
        category: Filter by category (e.g., 'growth', 'leadership')

    Returns:
        List of matching entries
    """
    if role_id:
        entries = get_entries_for_role(role_id)
    else:
        entries = get_all_entries()

    results = []

    for entry in entries:
        # Text filter
        if query:
            if query.lower() not in entry["text"].lower():
                continue

        # Tag filter
        if tags:
            entry_tags = entry.get("tags") or "[]"
            if isinstance(entry_tags, str):
                import json
                try:
                    entry_tags = json.loads(entry_tags)
                except:
                    entry_tags = []
            if not any(tag in entry_tags for tag in tags):
                continue

        # Category filter
        if category:
            if entry.get("category") != category:
                continue

        results.append(entry)

    return results


def get_entries_by_variant(variant: str) -> list[dict[str, Any]]:
    """
    Get corpus entries relevant to a resume variant.

    Args:
        variant: Resume variant (growth, ai-agentic, health-tech, etc.)

    Returns:
        List of entries tagged for that variant
    """
    # Variant to tag mappings
    variant_tags = {
        "growth": ["growth", "plg", "experimentation", "acquisition", "activation", "retention"],
        "ai-agentic": ["ai", "agentic", "orchestration", "automation", "multi-agent"],
        "health-tech": ["health-tech", "ehr", "clinical", "patient", "pharmacy"],
        "consumer": ["b2c", "consumer", "dtc", "marketplace"],
        "general": [],  # No specific tags - include all
    }

    tags = variant_tags.get(variant, [])

    if not tags:
        return get_all_entries()

    return search_corpus(tags=tags)
