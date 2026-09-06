"""The batched quick screen: request shape, answer parsing, and the run."""

import json

from jj import db, quick_screen


def _listings(n):
    return [
        {"id": i + 1, "url": f"https://x/{i + 1}", "title": f"PM {i + 1}", "company_name": "Acme",
         "location": "Austin, TX", "salary": "", "first_seen_at": "2026-09-01 10:00:00", "title_score": 60 - i}
        for i in range(n)
    ]


def test_build_request_names_every_ref_and_document():
    docs = {"present": {"constraints": "US only.", "corpus": "Roles: PM"}, "missing": ["preferences"]}
    text, refs = quick_screen.build_request(_listings(3), docs, instructions="INSTR")
    assert refs == ["L1", "L2", "L3"]
    assert text.startswith("INSTR")
    assert "L2: PM 2 | Acme | Austin, TX | first seen 2026-09-01" in text
    assert "L1, L2, L3" in text
    assert "### constraints" in text and "US only." in text
    assert "### corpus" in text


def test_parse_verdicts_tolerates_prose_and_names_problems():
    answer = 'Here you go:\n```json\n[{"ref":"L1","verdict":"Strong","reasoning":"yes"},' \
             '{"ref":"L2","verdict":"maybe","reasoning":"?"},{"ref":"L9","verdict":"no"},"junk"]\n```'
    verdicts, problems = quick_screen.parse_verdicts(answer, ["L1", "L2", "L3"])
    assert verdicts == {"L1": {"verdict": "strong", "reasoning": "yes"}}
    joined = " ".join(problems)
    assert "L2" in joined and "maybe" in joined
    assert "L9" in joined
    assert "L3: no verdict came back" in joined
    assert "row 4 was not an object" in joined


def test_parse_verdicts_no_json():
    verdicts, problems = quick_screen.parse_verdicts("I cannot help with that.", ["L1"])
    assert verdicts == {} and "no JSON array" in problems[0]


def test_batches_cap_at_100():
    items = list(range(250))
    assert [len(b) for b in quick_screen._batches(items, 100)] == [100, 100, 50]
    assert [len(b) for b in quick_screen._batches(items, 1000)] == [100, 100, 50]
    assert [len(b) for b in quick_screen._batches(items, 0)] == [1] * 250


def test_quick_screen_listings_with_fake_runner():
    calls = []

    def runner(prompt, model):
        calls.append(model)
        refs = [line.split(":")[0] for line in prompt.splitlines() if line.startswith("L") and ":" in line and "|" in line]
        rows = [{"ref": r, "verdict": "fair" if i % 2 else "no", "reasoning": r} for i, r in enumerate(refs)]
        return 0, json.dumps(rows), ""

    docs = {"present": {}, "missing": ["constraints", "preferences", "background"]}
    run = quick_screen.quick_screen_listings(
        _listings(5), model="haiku", batch_size=2, documents=docs, instructions="I", runner=runner,
    )
    assert run["batches"] == 3 and run["failed_batches"] == 0
    assert calls == ["haiku"] * 3
    assert len(run["verdicts"]) == 5
    assert run["verdicts"]["https://x/2"]["verdict"] == "fair"


def test_quick_screen_listings_failed_batch_is_reported():
    def runner(prompt, model):
        return 1, "", "boom"

    run = quick_screen.quick_screen_listings(
        _listings(2), model="haiku", batch_size=100, documents={"present": {}, "missing": []},
        instructions="I", runner=runner,
    )
    assert run["failed_batches"] == 1 and run["verdicts"] == {}
    assert "boom" in run["problems"][0]


def test_quick_screen_new_listings_end_to_end(jj_home):
    with db.get_connection() as conn:
        cid = conn.execute(
            "INSERT INTO companies (name, name_normalized, ats_type, is_target) VALUES ('Acme','acme','greenhouse',1)"
        ).lastrowid
        conn.commit()
    db.record_job_listing(cid, "https://acme/strong", title="Senior PM", location="Austin", title_score=80)
    db.record_job_listing(cid, "https://acme/fair", title="Growth Lead", location="Remote", title_score=40)
    db.record_job_listing(cid, "https://acme/no", title="Nurse", location="Austin", title_score=5)
    db.record_job_listing(cid, "https://acme/dup", title="PM", location="Austin", title_score=30)
    # A prospect already exists for the strong one (title gate passed earlier).
    app_id = db.create_application(
        company="Acme", position="Senior PM", job_url="https://acme/strong",
        status="prospect", fit_score=80, notes="Title Fit: 80. Via API scan.",
    )

    preview = quick_screen.quick_screen_new_listings(preview=True)
    assert preview["candidates"] == 4 and preview["batches_planned"] == 1
    assert preview["screened"] == 0 and "constraints" in preview["documents"]["missing"]

    def runner(prompt, model):
        return 0, json.dumps([
            {"ref": "L1", "verdict": "strong", "reasoning": "senior, Austin"},
            {"ref": "L2", "verdict": "fair", "reasoning": "worth a look"},
            {"ref": "L3", "verdict": "fair", "reasoning": "PM at a target"},
            {"ref": "L4", "verdict": "no", "reasoning": "not a PM role"},
        ]), ""

    q = quick_screen.quick_screen_new_listings(keep="fair", runner=runner, model="haiku")
    assert q["coverage"] == {"covered": 4, "total": 4}
    assert q["verdict_counts"] == {"no": 1, "weak": 0, "fair": 2, "strong": 1}
    assert q["kept"] == 3
    assert q["prospects"]["annotated"] == 1 and q["prospects"]["created"] == 1
    # "PM" at Acme fuzzy-matches the existing "Senior PM" row under a different
    # url: reported, not merged into that record.
    assert q["prospects"]["duplicate_of_other_url"] == 1
    assert q["dropped"] == [{"url": "https://acme/no", "reason": "judged no, below fair"}]

    # Verdicts stored, with provenance.
    j = db.get_best_judgment("https://acme/fair")
    assert j["judged_by"] == "model-quick" and j["model"] == "haiku" and j["prompt_version"]
    # The existing prospect kept its Title Fit head and gained the screen note.
    notes = db.get_application(app_id)["notes"]
    assert notes.startswith("Title Fit: 80.") and "Quick screen: strong." in notes
    # The new prospect exists for the fair one and none for the no.
    assert db.find_duplicate_application("Acme", "Growth Lead", "https://acme/fair")["job_url"] == "https://acme/fair"
    assert db.find_duplicate_application("Acme", "Nurse", "https://acme/no") is None
    assert db.get_best_judgment("https://acme/dup")["verdict"] == "fair"  # verdict kept even so
    # Nothing left to screen; a second run is a no-op with no model call.
    again = quick_screen.quick_screen_new_listings(runner=lambda *_: (_ for _ in ()).throw(AssertionError("called")))
    assert again["candidates"] == 0
