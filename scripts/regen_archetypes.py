"""Regenerate the 4 archetype master resumes after the MSK + MANGO refresh.

Mutates ~/.job-journal/archetypes.yaml in place:
- renames the role_bullets key 'AI Health-Tech Startup' -> 'GetHealthy.com'
- adds Memorial Sloan Kettering Cancer Center (current role) as the lead role
- swaps in the approved MANGO-positioned summaries (high-comp senior leader)
then regenerates each variant's Google Doc + PDF (strict mode, archetype),
marks the new resume rows is_archetype=1 (clearing prior ones per variant),
and writes the new resume_id / google_doc_id / pdf_path back to the yaml.

Roles in output (date-ordered, max_roles=6): MSK, GetHealthy.com, ZenBusiness,
Wellcore, Mattermost, Indeed. Clearhead is intentionally excluded (its
source-of-truth wording isn't in the corpus; strict mode needs corpus text).
"""
from pathlib import Path

from jj.config import load_archetypes, save_archetypes
from jj.db import get_connection
from jj.google_docs import generate_resume_programmatic

OLD_KEY = "AI Health-Tech Startup"
NEW_KEY = "GetHealthy.com"
MSK_KEY = "Memorial Sloan Kettering Cancer Center"

MSK_BULLETS = [
    "Improving conversion for new patients by ~20%, or helping thousands of new patients annually",
    "Creating a Web Optimization Strategy mindset and defining experimentation best practices for mskcc.org",
    "Increasing experimentation velocity and decreasing time to learnings from multiple months to weeks",
]

CLEARHEAD_KEY = "Clearhead / Accenture Interactive"
CLEARHEAD_BULLETS = [
    "Owned experimentation roadmaps and business metrics; delivered 400+ A/B tests with 36% win rate and 10x ROI",
    "Shipped SONOS checkout redesign generating $12MM YoY revenue impact, from conception through launch",
    "Managed cross-functional teams (Engineering, Design, Analytics) through agile product development for 15 enterprise clients",
]

# Approved MANGO-positioned summaries (high-comp senior leader; no banned
# phrases, no em-dashes).
SUMMARIES = {
    "general": (
        "Senior product leader who takes products from strategy through launch and proves impact on "
        "growth, retention, and revenue. Grew a consumer health platform from $100K to $1.8M ARR, drove "
        "self-serve signups 270% with activation from 8% to 25%, and scaled experimentation velocity across "
        "teams. Currently improving conversion for new cancer patients at Memorial Sloan Kettering. Operates "
        "with equal command of ambiguous 0-to-1 bets and optimization at scale."
    ),
    "growth": (
        "Growth product leader who scales acquisition, activation, and monetization through high-velocity "
        "experimentation. Drove signups 270% and activation from 8% to 25% at Mattermost, lifted new-customer "
        "conversion 33% at ZenBusiness, and scaled experimentation velocity up to 600% by building the testing "
        "infrastructure and prioritization frameworks teams run on. Now improving conversion for new patients "
        "at Memorial Sloan Kettering."
    ),
    "ai-agentic": (
        "Product leader building AI-native products and agentic systems from 0 to 1. Launched a multi-agent "
        "orchestration system of 5 specialized agents that interpret intent, reason through workflows, and "
        "execute autonomously across systems, and built AI-forward product processes using multi-agent "
        "workflows and MCP. Pairs that with growth at scale: 270% signup growth, experimentation velocity up "
        "to 600%, and event-driven platform integrations across distributed services."
    ),
    "health-tech": (
        "Product leader who builds and scales health-tech from 0 to 1 across clinical, growth, and AI. Built "
        "a fully integrated virtual care platform (EHR, pharmacy fulfillment, clinical operations across 51 "
        "states) and grew it from $100K to $1.8M ARR while cutting churn 60%. Currently improving conversion "
        "for new cancer patients at Memorial Sloan Kettering and designing multi-agent AI workflows for care "
        "management."
    ),
}

OUTPUT_DIR = Path.home() / "Documents" / "Resumes" / "archetypes"


def mutate_archetypes(data: dict) -> dict:
    for variant, az in data["archetypes"].items():
        # Summary
        if variant in SUMMARIES:
            az["summary"] = SUMMARIES[variant]
        rb = az.get("role_bullets", {})
        # Rename GetHealthy key (preserve its bullets)
        if OLD_KEY in rb and NEW_KEY not in rb:
            rb[NEW_KEY] = rb.pop(OLD_KEY)
        # Add MSK as a role (lead by date); same 3 bullets across variants
        rb[MSK_KEY] = list(MSK_BULLETS)
        # Add Clearhead (oldest main role) with corpus-valid bullets
        rb[CLEARHEAD_KEY] = list(CLEARHEAD_BULLETS)
        # Reorder so MSK is first in the dict (cosmetic; output order is by date)
        az["role_bullets"] = {MSK_KEY: rb.pop(MSK_KEY), **rb}
    return data


def free_old_archetypes() -> None:
    """Free the canonical archetype filenames (resumes.filename is UNIQUE) and
    demote prior archetype rows, so regeneration can insert fresh rows. Old rows
    are kept (not deleted) to preserve any application FK references."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, filename FROM resumes WHERE is_archetype = 1"
        ).fetchall()
        for r in rows:
            conn.execute(
                "UPDATE resumes SET filename = ?, is_archetype = 0 WHERE id = ?",
                (f"{r['filename']} [superseded {r['id']}]", r["id"]),
            )
        conn.commit()
        if rows:
            print(f"Freed {len(rows)} prior archetype filename(s).")


def set_archetype_flag(resume_id: int, variant: str) -> None:
    with get_connection() as conn:
        conn.execute("UPDATE resumes SET is_archetype = 0 WHERE variant = ? AND is_archetype = 1", (variant,))
        conn.execute("UPDATE resumes SET is_archetype = 1 WHERE id = ?", (resume_id,))
        conn.commit()


def main():
    data = load_archetypes()
    data = mutate_archetypes(data)
    data["generated_at"] = "2026-06-15"
    save_archetypes(data)
    print("archetypes.yaml mutated (summaries + GetHealthy rename + MSK lead).")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    free_old_archetypes()

    for variant, az in data["archetypes"].items():
        display = az.get("display_name", variant)
        print(f"\n=== Generating {variant} ({display}) ===")
        result = generate_resume_programmatic(
            company="Archetype",
            position=display,
            variant=variant,
            mode="strict",
            custom_summary=az["summary"],
            custom_skills=az["skills"],
            role_bullets=az["role_bullets"],
            max_roles=7,
            generation_mode="archetype",
            output_dir=OUTPUT_DIR,
            auto_open=False,
            keep_google_doc=True,
            export_pdf=True,
        )
        if not result.success:
            print(f"  FAILED: {result.error}")
            continue
        set_archetype_flag(result.resume_id, variant)
        az["resume_id"] = result.resume_id
        az["google_doc_id"] = result.doc_id
        az["pdf_path"] = str(result.pdf_path) if result.pdf_path else az.get("pdf_path")
        print(f"  OK resume_id={result.resume_id} pdf={result.pdf_path}")
        save_archetypes(data)  # persist metadata incrementally

    print("\nDone. archetypes.yaml updated with new ids/paths.")


if __name__ == "__main__":
    main()
