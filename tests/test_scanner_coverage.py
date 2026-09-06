"""scan_all_api_companies reports coverage as a fraction and names zero-yield companies."""

from jj import ats_scanner


def test_scan_summary_coverage_and_zero_yield(monkeypatch):
    def fake_scanner(slug):
        if slug == "good":
            return [{"title": "PM", "url": "https://good/1", "location": "Austin"}]
        if slug == "gone":
            ats_scanner._last_fetch_error = "HTTP 404"
            return []
        if slug == "boom":
            raise RuntimeError("kaboom")
        return []

    monkeypatch.setitem(ats_scanner._SCANNERS, "greenhouse", fake_scanner)
    companies = [
        {"id": 1, "name": "Good", "ats_type": "greenhouse", "careers_url": "https://boards.greenhouse.io/good"},
        {"id": 2, "name": "Gone", "ats_type": "greenhouse", "careers_url": "https://boards.greenhouse.io/gone"},
        {"id": 3, "name": "Empty", "ats_type": "greenhouse", "careers_url": "https://boards.greenhouse.io/empty"},
        {"id": 4, "name": "NoSlug", "ats_type": "greenhouse", "careers_url": "https://example.com/careers"},
        {"id": 5, "name": "Boom", "ats_type": "greenhouse", "careers_url": "https://boards.greenhouse.io/boom"},
        {"id": 6, "name": "Unknown", "ats_type": "workday", "careers_url": "https://x"},
    ]
    results = ats_scanner.scan_all_api_companies(companies)
    summary = results["_summary"]
    assert results[1][0]["company_name"] == "Good"
    assert summary["coverage"] == {"covered": 1, "total": 6}
    assert summary["companies_with_errors"] == 1
    reasons = {z["name"]: z["reason"] for z in summary["zero_yield"]}
    assert reasons["Gone"] == "HTTP 404: slug likely wrong"
    assert reasons["Empty"] == "empty board"
    assert reasons["NoSlug"] == "no slug in careers_url"
    assert reasons["Boom"].startswith("error: RuntimeError")
    assert "no scanner" in reasons["Unknown"]
