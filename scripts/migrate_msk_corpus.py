"""One-off migration: reconcile corpus DB to the 2026-06-09 source-of-truth resume.

- Add Memorial Sloan Kettering Cancer Center role (Mar 2026-current) + 3 bullets
- Rename role 'AI Health-Tech Startup' -> 'GetHealthy.com', fix its dates/location
- Fix Wellcore and ZenBusiness end dates to match the source-of-truth resume

Idempotent-ish: skips MSK creation if the role already exists.
"""
from jj.db import create_role, create_entry, find_role_by_company_title, get_connection

MSK_BULLETS = [
    "Improving conversion for new patients by ~20%, or helping thousands of new patients annually",
    "Creating a Web Optimization Strategy mindset and defining experimentation best practices for mskcc.org",
    "Increasing experimentation velocity and decreasing time to learnings from multiple months to weeks",
]

def main():
    # 1. Fix dates / rename existing roles (by id, verified beforehand)
    with get_connection() as conn:
        # Rename GetHealthy (role id 1, was 'AI Health-Tech Startup')
        conn.execute(
            "UPDATE roles SET company=?, location=?, start_date=?, end_date=?, is_current=0 "
            "WHERE id=1 AND company='AI Health-Tech Startup'",
            ("GetHealthy.com", "Austin, TX", "2025-11-01", "2025-12-01"),
        )
        # ZenBusiness (id 2): end -> 2025-09
        conn.execute(
            "UPDATE roles SET start_date='2025-01-01', end_date='2025-09-01' WHERE id=2",
        )
        # Wellcore (id 3): end -> 2024-09
        conn.execute(
            "UPDATE roles SET start_date='2023-05-01', end_date='2024-09-01' WHERE id=3",
        )
        conn.commit()

    # 2. Add MSK role + bullets (skip if present)
    existing = find_role_by_company_title(
        "Memorial Sloan Kettering Cancer Center", "Principal Product Manager (Consultant)"
    )
    if existing:
        print(f"MSK role already exists (id={existing['id']}); skipping create.")
        msk_id = existing["id"]
    else:
        msk_id = create_role(
            title="Principal Product Manager (Consultant)",
            company="Memorial Sloan Kettering Cancer Center",
            location="Remote",
            start_date="2026-03-01",
            end_date=None,
            is_current=True,
            tags=["health-tech", "experimentation", "conversion", "cro", "growth", "patient"],
        )
        for b in MSK_BULLETS:
            create_entry(
                role_id=msk_id,
                text=b,
                category="Conversion/Experimentation",
                tags=["health-tech", "experimentation", "conversion", "cro", "growth"],
                source="base.md",
            )
        print(f"Created MSK role id={msk_id} with {len(MSK_BULLETS)} bullets.")

    # 3. Verify
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, company, start_date, end_date, is_current FROM roles "
            "WHERE id IN (1,2,3) OR company LIKE 'Memorial%' ORDER BY start_date DESC"
        ).fetchall()
        print("\nRoles after migration:")
        for r in rows:
            print(f"  [{r['id']}] {r['company']:40s} {r['start_date']} -> {r['end_date']} cur={r['is_current']}")
        n = conn.execute("SELECT COUNT(*) c FROM entries WHERE role_id=?", (msk_id,)).fetchone()["c"]
        print(f"\nMSK entries: {n}")

if __name__ == "__main__":
    main()
