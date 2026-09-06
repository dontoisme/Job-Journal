"""The judgments table: upsert, precedence, listing, and prospect selection."""

import pytest

from jj import db


def _company(name="Acme", is_target=1, priority=2):
    with db.get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO companies (name, name_normalized, careers_url, ats_type, is_target, target_priority) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (name, name.lower(), f"https://boards.greenhouse.io/{name.lower()}", "greenhouse", is_target, priority),
        )
        conn.commit()
        return cur.lastrowid


def test_record_judgment_upserts_per_source(jj_home):
    url = "https://example.com/j/1"
    first = db.record_judgment(url, "weak", "thin facts", judged_by="model-quick", model="haiku")
    second = db.record_judgment(url, "fair", "better", judged_by="model-quick", model="haiku")
    assert first == second
    rows = db.get_judgments_for_url(url)
    assert len(rows) == 1
    assert rows[0]["verdict"] == "fair"
    assert rows[0]["reasoning"] == "better"


def test_bad_verdict_and_source_are_loud(jj_home):
    with pytest.raises(ValueError):
        db.record_judgment("https://x", "maybe")
    with pytest.raises(ValueError):
        db.record_judgment("https://x", "fair", judged_by="robot")
    with pytest.raises(ValueError):
        db.record_judgment("", "fair")


def test_precedence_user_over_full_over_quick(jj_home):
    url = "https://example.com/j/2"
    db.record_judgment(url, "strong", judged_by="model-quick")
    assert db.get_best_judgment(url)["judged_by"] == "model-quick"
    db.record_judgment(url, "fair", judged_by="model-full")
    assert db.get_best_judgment(url)["judged_by"] == "model-full"
    db.record_judgment(url, "no", "I know this team", judged_by="user")
    best = db.get_best_judgment(url)
    assert best["judged_by"] == "user" and best["verdict"] == "no"
    assert [j["judged_by"] for j in db.get_judgments_for_url(url)] == ["user", "model-full", "model-quick"]


def test_list_filter_delete_and_counts(jj_home):
    db.record_judgment("https://a", "strong", judged_by="model-quick")
    db.record_judgment("https://b", "no", judged_by="model-quick")
    db.record_judgment("https://b", "weak", judged_by="user")
    assert len(db.list_judgments()) == 3
    assert [r["url"] for r in db.list_judgments(verdict="strong")] == ["https://a"]
    assert len(db.list_judgments(judged_by="user")) == 1
    counts = db.get_judgment_counts()
    assert counts["model-quick"] == {"strong": 1, "no": 1}
    assert db.delete_judgments("https://b", judged_by="user") == 1
    assert db.delete_judgments("https://b") == 1
    assert db.delete_judgments("https://b") == 0


def test_unscreened_listings_rank_by_title_score(jj_home):
    cid = _company()
    db.record_job_listing(cid, "https://acme/1", title="Senior PM", location="Austin", title_score=85)
    db.record_job_listing(cid, "https://acme/2", title="PM", location="Remote US", title_score=45)
    db.record_job_listing(cid, "https://acme/3", title="Mystery", location=None)  # no score
    db.record_job_listing(cid, "https://acme/4", title="Screened", title_score=99)
    db.record_judgment("https://acme/4", "no", judged_by="model-quick")
    rows = db.get_unscreened_listings(limit=10)
    assert [r["url"] for r in rows] == ["https://acme/1", "https://acme/2", "https://acme/3"]
    assert rows[0]["company_name"] == "Acme"
    # A person's verdict also takes a listing out of the queue.
    db.record_judgment("https://acme/1", "no", judged_by="user")
    assert [r["url"] for r in db.get_unscreened_listings()] == ["https://acme/2", "https://acme/3"]
    # Re-recording a listing keeps a known title score when none is passed.
    db.record_job_listing(cid, "https://acme/2", title="PM")
    assert db.get_unscreened_listings()[0]["title_score"] == 45


def test_quick_screened_prospects_selection(jj_home):
    _company("Acme", is_target=1, priority=2)
    _company("Other", is_target=0, priority=0)

    def prospect(company, url, score):
        return db.create_application(
            company=company, position="Senior PM", job_url=url, status="prospect",
            fit_score=score, notes=f"Title Fit: {score}. Quick screen: fair.",
        )

    prospect("Other", "https://o/strong", 40)
    prospect("Acme", "https://a/fair", 60)
    prospect("Other", "https://o/fair", 70)
    prospect("Other", "https://o/weak", 90)
    prospect("Other", "https://o/full", 90)
    db.record_judgment("https://o/strong", "strong", judged_by="model-quick")
    db.record_judgment("https://a/fair", "fair", judged_by="model-quick")
    db.record_judgment("https://o/fair", "fair", judged_by="model-quick")
    db.record_judgment("https://o/weak", "weak", judged_by="model-quick")
    db.record_judgment("https://o/full", "strong", judged_by="model-quick")
    db.record_judgment("https://o/full", "fair", judged_by="model-full")

    picks = db.get_quick_screened_prospects(min_verdict="fair", limit=10)
    # strong first, then target company, then title score; full-read one excluded
    assert [p["job_url"] for p in picks] == ["https://o/strong", "https://a/fair", "https://o/fair"]
    assert picks[0]["quick_verdict"] == "strong"
    assert [p["job_url"] for p in db.get_quick_screened_prospects(min_verdict="strong")] == ["https://o/strong"]
    assert len(db.get_quick_screened_prospects(min_verdict="weak")) == 4
    assert db.get_quick_screened_prospects(min_verdict="bogus") == []
