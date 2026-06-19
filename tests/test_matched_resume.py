"""Unit tests for the 'matched' resume-format helpers.

These exercise the pure, deterministic helpers in jj.google_docs that power the
matched format: 5-year role compression with a minimum-role floor, JD-exact
skill matching (substantiated-only), bullet story-ordering, and Earlier
Experience rendering. They touch no DB, Google API, or network.
"""

from datetime import datetime

from jj.google_docs import (
    build_matched_skills,
    order_bullets_for_story,
    roles_to_earlier_dicts,
    split_roles_by_window,
)

# A trimmed, date-ordered (recent-first) stand-in for Don's non-project roles.
ROLES = [
    {"company": "Memorial Sloan Kettering", "title": "Principal PM", "location": "NY",
     "start_date": "2026-03", "end_date": None, "is_current": True},
    {"company": "ZenBusiness, Inc.", "title": "Staff PM, Growth", "location": "Austin, TX",
     "start_date": "2025-01", "end_date": "2025-09", "is_current": False},
    {"company": "Wellcore", "title": "Head of Product", "location": "Austin, TX",
     "start_date": "2023-05", "end_date": "2024-09", "is_current": False},
    {"company": "Mattermost", "title": "Principal PM, Growth", "location": "Remote",
     "start_date": "2021-11", "end_date": "2023-02", "is_current": False},
    {"company": "Indeed", "title": "Web Optimization Manager", "location": "Austin, TX",
     "start_date": "2018-07", "end_date": "2021-11", "is_current": False},
    {"company": "Clearhead / Accenture Interactive", "title": "Optimization Director",
     "location": "Austin, TX", "start_date": "2017-01", "end_date": "2018-08", "is_current": False},
    {"company": "SpareFoot", "title": "Product Manager", "location": "Austin, TX",
     "start_date": "2015-05", "end_date": "2016-11", "is_current": False},
]

TODAY = datetime(2026, 6, 18)


# --- 5-year window split + floor ------------------------------------------

def test_window_keeps_near_cutoff_role_and_demotes_older():
    main, earlier = split_roles_by_window(ROLES, TODAY, max_years_lookback=5, min_roles=4)
    main_companies = {r["company"] for r in main}
    earlier_companies = {r["company"] for r in earlier}

    # Mattermost (2021-11) is inside the 5yr window (cutoff 2021-06) -> stays.
    assert "Mattermost" in main_companies
    # Indeed / Clearhead / SpareFoot are older -> demoted to Earlier Experience.
    assert {"Indeed", "Clearhead / Accenture Interactive", "SpareFoot"} <= earlier_companies
    # No role is lost or duplicated across the split.
    assert len(main) + len(earlier) == len(ROLES)


def test_window_floor_promotes_when_too_few_in_window():
    recent_only = ROLES[:1]  # just MSK is "current"
    older = ROLES[4:]        # Indeed, Clearhead, SpareFoot (all pre-cutoff)
    roles = recent_only + older
    main, earlier = split_roles_by_window(roles, TODAY, max_years_lookback=5, min_roles=3)
    # Only 1 role is in-window, so the floor promotes the 2 most-recent older ones.
    assert len(main) == 3
    assert main[0]["company"] == "Memorial Sloan Kettering"
    # SpareFoot is the least recent, so it is the one left in earlier.
    assert [r["company"] for r in earlier] == ["SpareFoot"]


def test_earlier_dicts_shape_and_dates():
    _, earlier = split_roles_by_window(ROLES, TODAY)
    dicts = roles_to_earlier_dicts(earlier)
    assert all({"company", "title", "location", "dates"} <= d.keys() for d in dicts)
    spare = next(d for d in dicts if d["company"] == "SpareFoot")
    # Title-only rendering carries a human date range, never an em-dash.
    assert spare["dates"]
    assert "—" not in spare["dates"]


# --- JD-exact skill matching (substantiated only) -------------------------

SKILLS_BY_CATEGORY = {
    "growth-&-experimentation": ["Funnel Optimization", "Growth Loops", "Growth Strategy"],
    "analytics-&-tools": ["Amplitude", "Mixpanel", "SQL", "Segment CDP"],
    "product-management": ["Product Strategy", "Roadmap Ownership"],
}


def test_unsubstantiated_jd_term_is_dropped():
    jd_terms = ["Funnel Optimization", "Kubernetes administration"]
    out = build_matched_skills(jd_terms, SKILLS_BY_CATEGORY)
    flat = [s for terms in out.values() for s in terms]
    assert "Funnel Optimization" in flat
    # No corpus backing for Kubernetes -> never emitted (no keyword stuffing).
    assert not any("kubernetes" in s.lower() for s in flat)


def test_jd_exact_wording_is_preserved():
    # JD phrases a skill Don has slightly differently; we keep the JD's wording.
    jd_terms = ["funnel optimization", "A/B experimentation"]
    out = build_matched_skills(jd_terms, SKILLS_BY_CATEGORY, threshold=0.4)
    flat = [s for terms in out.values() for s in terms]
    assert "funnel optimization" in flat  # lower-case JD wording, not "Funnel Optimization"


def test_dropped_role_skills_are_substantiating():
    # A skill not in the canonical categories but demonstrated by a dropped role
    # (passed via extra_skill_pool) can still substantiate a JD term.
    jd_terms = ["conversion rate optimization"]
    out = build_matched_skills(
        jd_terms, SKILLS_BY_CATEGORY,
        extra_skill_pool=["conversion-rate-optimization", "enterprise"],
        threshold=0.7,
    )
    flat = [s for terms in out.values() for s in terms]
    assert "conversion rate optimization" in flat


def test_categories_capped_at_five():
    big = {f"cat-{i}": [f"Skill {i}"] for i in range(8)}
    jd_terms = [f"Skill {i}" for i in range(8)]
    out = build_matched_skills(jd_terms, big, max_categories=5)
    assert len(out) <= 5


# --- bullet story-ordering ------------------------------------------------

BULLETS = [
    "Grew self-serve signups 270% and activation from 8% to 25%",
    "Built experimentation platform increasing testing velocity 600%",
    "Partnered with Sales and Marketing on lifecycle and cross-sell motions",
]


def test_story_ordering_is_a_permutation():
    reqs = ["partner with sales and marketing on growth", "drive activation and signups"]
    out = order_bullets_for_story(BULLETS, reqs)
    assert sorted(out) == sorted(BULLETS)
    assert len(out) == len(BULLETS)


def test_story_ordering_leads_with_top_requirement():
    reqs = ["partner with sales and marketing", "build experimentation infrastructure"]
    out = order_bullets_for_story(BULLETS, reqs)
    # The Sales/Marketing bullet best answers the #1 requirement, so it leads.
    assert out[0] == "Partnered with Sales and Marketing on lifecycle and cross-sell motions"


def test_story_ordering_no_requirements_is_identity():
    assert order_bullets_for_story(BULLETS, []) == BULLETS
