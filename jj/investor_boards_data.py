"""Curated seed data for VC/investor portfolio job boards."""

import json

from jj.db import create_investor_board

INVESTOR_BOARDS = [
    # --- Major VC Firms ---
    {
        "name": "Andreessen Horowitz (a16z)",
        "short_name": "a16z",
        "board_url": "https://jobs.a16z.com/jobs",
        "board_type": "vc",
        "investor_type": "multi_stage",
        "has_talent_network": True,
        "talent_network_url": "https://talentplace.a16z.com",
        "portfolio_focus": json.dumps(["ai", "enterprise", "fintech", "crypto", "health"]),
    },
    {
        "name": "Sequoia Capital",
        "short_name": "Sequoia",
        "board_url": "https://jobs.sequoiacap.com/jobs/",
        "board_type": "vc",
        "investor_type": "multi_stage",
        "portfolio_focus": json.dumps(["ai", "enterprise", "consumer", "health"]),
    },
    {
        "name": "Greylock Partners",
        "short_name": "Greylock",
        "board_url": "https://jobs.greylock.com/",
        "board_type": "vc",
        "investor_type": "early_stage",
        "has_talent_network": True,
        "talent_network_url": "https://greylock.com/talent-network/",
        "portfolio_focus": json.dumps(["ai", "enterprise", "consumer"]),
    },
    {
        "name": "Lightspeed Venture Partners",
        "short_name": "LSVP",
        "board_url": "https://jobs.lsvp.com/jobs",
        "board_type": "vc",
        "investor_type": "multi_stage",
        "portfolio_focus": json.dumps(["ai", "enterprise", "consumer", "health"]),
    },
    {
        "name": "Accel",
        "short_name": "Accel",
        "board_url": "https://jobs.accel.com/jobs",
        "board_type": "vc",
        "investor_type": "early_stage",
        "portfolio_focus": json.dumps(["ai", "enterprise", "fintech"]),
    },
    {
        "name": "Bessemer Venture Partners",
        "short_name": "Bessemer",
        "board_url": "https://jobs.bvp.com/jobs",
        "board_type": "vc",
        "investor_type": "multi_stage",
        "portfolio_focus": json.dumps(["ai", "enterprise", "health", "fintech"]),
    },
    {
        "name": "Index Ventures",
        "short_name": "Index",
        "board_url": "https://indexventures.com/startup-jobs",
        "board_type": "vc",
        "investor_type": "multi_stage",
        "portfolio_focus": json.dumps(["ai", "enterprise", "fintech", "consumer"]),
    },
    {
        "name": "Kleiner Perkins",
        "short_name": "KP",
        "board_url": "https://jobs.kleinerperkins.com/companies",
        "board_type": "vc",
        "investor_type": "early_stage",
        "portfolio_focus": json.dumps(["ai", "enterprise", "health", "climate"]),
    },
    {
        "name": "NEA",
        "short_name": "NEA",
        "board_url": "https://careers.nea.com/",
        "board_type": "vc",
        "investor_type": "multi_stage",
        "portfolio_focus": json.dumps(["ai", "enterprise", "health"]),
    },
    {
        "name": "General Catalyst",
        "short_name": "GC",
        "board_url": "https://jobs.generalcatalyst.com/jobs",
        "board_type": "vc",
        "investor_type": "multi_stage",
        "has_talent_network": True,
        "talent_network_url": "https://jobs.generalcatalyst.com/talent-network",
        "portfolio_focus": json.dumps(["ai", "enterprise", "health", "fintech"]),
    },
    {
        "name": "Insight Partners",
        "short_name": "Insight",
        "board_url": "https://jobs.insightpartners.com/jobs",
        "board_type": "growth_equity",
        "investor_type": "growth",
        "has_talent_network": True,
        "talent_network_url": "https://jobs.insightpartners.com/talent-network",
        "portfolio_focus": json.dumps(["enterprise", "ai", "fintech"]),
    },
    {
        "name": "Coatue Management",
        "short_name": "Coatue",
        "board_url": "https://jobs.coatue.com/companies",
        "board_type": "growth_equity",
        "investor_type": "growth",
        "portfolio_focus": json.dumps(["ai", "enterprise", "consumer"]),
    },
    {
        "name": "Thrive Capital",
        "short_name": "Thrive",
        "board_url": "https://jobs.thrivecap.com/jobs",
        "board_type": "vc",
        "investor_type": "multi_stage",
        "portfolio_focus": json.dumps(["ai", "enterprise", "consumer"]),
    },
    {
        "name": "Sapphire Ventures",
        "short_name": "Sapphire",
        "board_url": "https://jobs.sapphireventures.com/jobs",
        "board_type": "vc",
        "investor_type": "growth",
        "portfolio_focus": json.dumps(["enterprise", "ai"]),
    },
    {
        "name": "Battery Ventures",
        "short_name": "Battery",
        "board_url": "https://jobs.battery.com/jobs",
        "board_type": "vc",
        "investor_type": "multi_stage",
        "portfolio_focus": json.dumps(["enterprise", "ai", "fintech"]),
    },
    {
        "name": "Emergence Capital",
        "short_name": "Emergence",
        "board_url": "https://talent.emcap.com/jobs",
        "board_type": "vc",
        "investor_type": "early_stage",
        "portfolio_focus": json.dumps(["enterprise", "ai"]),
    },
    {
        "name": "OpenView Partners",
        "short_name": "OpenView",
        "board_type": "vc",
        "investor_type": "growth",
        "has_talent_network": True,
        "talent_network_url": "https://openviewpartners.com/openview-talent/",
        "talent_network_notes": "No centralized job board; talent network is primary entry point",
        "portfolio_focus": json.dumps(["enterprise", "plg"]),
        "is_active": False,
        "notes": "No centralized job board found",
    },
    {
        "name": "Craft Ventures",
        "short_name": "Craft",
        "board_url": "https://jobs.craftventures.com/jobs",
        "board_type": "vc",
        "investor_type": "early_stage",
        "has_talent_network": True,
        "talent_network_url": "https://jobs.craftventures.com/talent-network",
        "portfolio_focus": json.dumps(["enterprise", "ai", "fintech"]),
    },
    {
        "name": "First Round Capital",
        "short_name": "First Round",
        "board_url": "https://jobs.firstround.com/",
        "board_type": "vc",
        "investor_type": "seed",
        "portfolio_focus": json.dumps(["enterprise", "ai", "consumer"]),
    },
    {
        "name": "Union Square Ventures",
        "short_name": "USV",
        "board_url": "https://jobs.usv.com",
        "board_type": "vc",
        "investor_type": "early_stage",
        "portfolio_focus": json.dumps(["ai", "crypto", "consumer"]),
    },
    {
        "name": "Y Combinator",
        "short_name": "YC",
        "board_url": "https://workatastartup.com/",
        "board_type": "accelerator",
        "investor_type": "seed",
        "has_talent_network": True,
        "talent_network_url": "https://workatastartup.com",
        "talent_network_notes": "Single application covers all YC companies",
        "portfolio_focus": json.dumps(["ai", "enterprise", "consumer", "health", "fintech"]),
    },
    {
        "name": "Redpoint Ventures",
        "short_name": "Redpoint",
        "board_url": "https://careers.redpoint.com/jobs",
        "board_type": "vc",
        "investor_type": "early_stage",
        "has_talent_network": True,
        "talent_network_url": "https://careers.redpoint.com/talent-network",
        "portfolio_focus": json.dumps(["enterprise", "ai", "consumer"]),
    },
    {
        "name": "Felicis Ventures",
        "short_name": "Felicis",
        "board_url": "https://jobs.felicis.com/jobs",
        "board_type": "vc",
        "investor_type": "early_stage",
        "portfolio_focus": json.dumps(["ai", "enterprise", "health", "fintech"]),
    },
    {
        "name": "Madrona Ventures",
        "short_name": "Madrona",
        "board_url": "https://jobs.madrona.com/jobs",
        "board_type": "vc",
        "investor_type": "early_stage",
        "geo_focus": "Pacific Northwest",
        "portfolio_focus": json.dumps(["ai", "enterprise"]),
    },
    # --- PE / Growth Equity ---
    {
        "name": "Francisco Partners",
        "short_name": "FP",
        "board_url": "https://careers.franciscopartners.com/jobs",
        "board_type": "pe",
        "investor_type": "growth",
        "has_talent_network": True,
        "talent_network_url": "https://careers.franciscopartners.com/talent-network",
        "portfolio_focus": json.dumps(["enterprise", "fintech"]),
    },
    {
        "name": "Vista Equity Partners",
        "short_name": "Vista",
        "board_url": "https://vistaequitypartners.com/careers/",
        "board_type": "pe",
        "investor_type": "growth",
        "portfolio_focus": json.dumps(["enterprise"]),
    },
    # --- Austin-Local ---
    {
        "name": "S3 Ventures",
        "short_name": "S3",
        "board_url": "https://jobs.s3vc.com/jobs",
        "board_type": "vc",
        "investor_type": "early_stage",
        "geo_focus": "Texas",
        "portfolio_focus": json.dumps(["enterprise", "health"]),
    },
    {
        "name": "Silverton Partners",
        "short_name": "Silverton",
        "board_url": "https://jobs.silvertonpartners.com/jobs",
        "board_type": "vc",
        "investor_type": "early_stage",
        "geo_focus": "Texas",
        "portfolio_focus": json.dumps(["enterprise", "consumer"]),
    },
    {
        "name": "LiveOak Venture Partners",
        "short_name": "LiveOak",
        "board_url": "https://jobs.liveoakvp.com/jobs",
        "board_type": "vc",
        "investor_type": "early_stage",
        "geo_focus": "Texas",
        "portfolio_focus": json.dumps(["enterprise", "health"]),
    },
    {
        "name": "ATX Venture Partners",
        "short_name": "ATX VP",
        "board_url": "https://jobs.atxventurepartners.com/jobs",
        "board_type": "vc",
        "investor_type": "early_stage",
        "geo_focus": "Texas",
        "portfolio_focus": json.dumps(["enterprise", "ai"]),
    },
    # --- Firms with no board found (inactive) ---
    {
        "name": "Benchmark Capital",
        "short_name": "Benchmark",
        "board_type": "vc",
        "investor_type": "early_stage",
        "is_active": False,
        "notes": "No centralized job board found",
        "portfolio_focus": json.dumps(["enterprise", "consumer"]),
    },
    {
        "name": "Tiger Global Management",
        "short_name": "Tiger Global",
        "board_type": "growth_equity",
        "investor_type": "growth",
        "is_active": False,
        "notes": "No centralized job board found",
        "portfolio_focus": json.dumps(["enterprise", "consumer"]),
    },
    {
        "name": "Thoma Bravo",
        "short_name": "Thoma Bravo",
        "board_type": "pe",
        "investor_type": "growth",
        "is_active": False,
        "notes": "No centralized job board found",
        "portfolio_focus": json.dumps(["enterprise"]),
    },
    {
        "name": "Hellman & Friedman",
        "short_name": "H&F",
        "board_type": "pe",
        "investor_type": "late_stage",
        "is_active": False,
        "notes": "No centralized job board found",
        "portfolio_focus": json.dumps(["enterprise", "fintech"]),
    },
    {
        "name": "Founders Fund",
        "short_name": "FF",
        "board_type": "vc",
        "investor_type": "multi_stage",
        "is_active": False,
        "notes": "No centralized job board found",
        "portfolio_focus": json.dumps(["ai", "enterprise", "health"]),
    },
]


def seed_investor_boards() -> dict[str, int]:
    """Upsert all investor boards from seed data.
    Returns {'created': N, 'skipped': N}."""
    from jj.db import get_investor_board_by_name

    created = 0
    skipped = 0

    for board in INVESTOR_BOARDS:
        name = board["name"]
        board_url = board.get("board_url")

        # Check if it already exists before creating
        existing = get_investor_board_by_name(name)
        if existing:
            skipped += 1
            continue

        kwargs = {k: v for k, v in board.items() if k not in ("name", "board_url")}
        create_investor_board(name, board_url, **kwargs)
        created += 1

    return {"created": created, "skipped": skipped}
