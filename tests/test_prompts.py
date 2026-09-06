"""The verdict scale, the fit bands, and the profile documents."""

from jj import prompts


def test_verdict_scale_is_ordered():
    assert prompts.VERDICTS == ("no", "weak", "fair", "strong")
    assert prompts.rank_of("strong") > prompts.rank_of("fair") > prompts.rank_of("weak") > prompts.rank_of("no")
    assert prompts.rank_of("maybe") == -1
    assert prompts.is_verdict(" Fair ")
    assert not prompts.is_verdict("maybe")


def test_at_or_above_and_drop_reason():
    assert prompts.at_or_above("strong", "fair")
    assert prompts.at_or_above("fair", "fair")
    assert not prompts.at_or_above("weak", "fair")
    assert not prompts.at_or_above("bogus", "fair")
    assert prompts.drop_reason("weak", "strong") == "judged weak, below strong"


def test_fit_bands_map_scores_to_verdicts():
    assert prompts.verdict_from_score(92) == "strong"
    assert prompts.verdict_from_score(80) == "strong"
    assert prompts.verdict_from_score(79) == "fair"
    assert prompts.verdict_from_score(65) == "fair"
    assert prompts.verdict_from_score(50) == "weak"
    assert prompts.verdict_from_score(12) == "no"
    assert prompts.verdict_from_score(None) == "no"
    assert prompts.band_label(70) == "Good Fit"


def test_fit_rubric_sums_to_100_and_prints():
    assert sum(points for _, _, points in prompts.FIT_RUBRIC_CATEGORIES) == 100
    text = prompts.fit_rubric_text()
    assert "Skills Match: 0-35" in text
    assert prompts.PROMPT_VERSION in text


def test_profile_documents_report_missing(jj_home):
    docs = prompts.load_profile_documents()
    assert docs["present"] == {}
    assert set(docs["missing"]) == set(prompts.PROFILE_DOCUMENTS)
    (jj_home / "constraints.md").write_text("No roles outside the US.\n")
    (jj_home / "preferences.md").write_text("   \n")  # whitespace counts as missing
    docs = prompts.load_profile_documents()
    assert docs["present"] == {"constraints": "No roles outside the US."}
    assert "preferences" in docs["missing"]
    lines = prompts.describe_missing_documents(docs["missing"])
    assert any("preferences" in line for line in lines)


def test_quick_screen_prompt_override(jj_home):
    text, source = prompts.load_quick_screen_prompt()
    assert source == "shipped"
    assert "JSON array" in text
    (jj_home / "quick-screen-prompt.md").write_text("   \n")
    assert prompts.load_quick_screen_prompt()[1] == "shipped"
    (jj_home / "quick-screen-prompt.md").write_text("My own instructions.\n")
    text, source = prompts.load_quick_screen_prompt()
    assert text.strip() == "My own instructions."
    assert source.endswith("quick-screen-prompt.md")


def test_render_prompt_names():
    for name in prompts.PROMPT_NAMES:
        assert prompts.render_prompt(name)
    try:
        prompts.render_prompt("nope")
    except KeyError:
        pass
    else:
        raise AssertionError("unknown prompt name should raise KeyError")
