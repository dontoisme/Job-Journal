# Quick Screen: the tier between the title rule and the full score

> **Status:** experimental (branch `claude/job-journal-pinloop-comparison-w3mue1`).
> **Origin:** adopted from Pinloop CLI's `judge --quick` (see [comparison-pinloop-cli.md](comparison-pinloop-cli.md), items 6.3 through 6.8).

## Why

Until now a new listing met a hard gate before anything else happened: `score_title_fit` had to return 50 or more, a product-management role type, and a US location, or the listing was dropped silently (`skipped_title`). Anything that passed went to a 15-minute `/slack-apply` spawn, which is why `jj/scoring.py` needs a 15-per-day ceiling.

The quick screen turns the title rule into a ranking and adds a cheap model tier between it and the full score:

```
score_title_fit          free, deterministic   ranks every new listing
      |
jj monitor quick-screen  one Haiku call per 50-100 listings, plain facts only
      |                  verdict: no | weak | fair | strong, with one sentence
      |                  fair/strong -> prospect
jj monitor score-new     full JD read, 4-category rubric, archetype link
                         quick-screened prospects first, strong before fair
```

Pinloop's measured ratio for the same shape is about 14:1, so screening a hundred listings costs roughly what seven full scores cost.

## Commands

```bash
jj monitor quick-screen --preview            # what would be sent and to which model; calls nothing
jj monitor quick-screen                      # screen up to 100 unscreened listings, store verdicts, create prospects
jj monitor quick-screen --limit 200 --keep strong --model sonnet
jj monitor quick-screen --json               # one JSON object on stdout

jj monitor scan-apis --quick-screen --score-new --score-limit 3   # the launcher's daily shape
jj monitor score-new --preview               # which prospects a full-score run would read, and the budget
jj monitor score-new --quick-only            # never fall back to the title-rule picks

jj judgments list --reasoning                # every stored verdict, newest first, who made it
jj judgments put <url> --verdict no --reasoning "already talked to this team"
```

## What the screen sends

For each listing: a reference (`L1`, `L2`, ...), title, company, location, pay when stored, and first-seen date. Never the job description. Then the profile:

| Document | Path | Meaning to the model |
|----------|------|----------------------|
| `constraints` | `~/.job-journal/constraints.md` | Rules that cannot be broken (authorization, geography, comp floor, roles never wanted). A broken rule is `no`, whatever else is true, and the reasoning must name the rule. |
| `preferences` | `~/.job-journal/preferences.md` | Wants and does-not-wants. |
| `background` | `~/.job-journal/background.md` | What the person has done, in their words. |
| `corpus` | built from `roles` + `skills` in the DB | Most recent roles and the skill list. |
| `profile` | built from `profile.yaml` | Location, authorization, remote preference, years. |

Every missing document is named in the run summary with what the model therefore could not do. The instructions themselves ship in `jj/prompts.py` (`DEFAULT_QUICK_SCREEN_PROMPT`); a non-empty `~/.job-journal/quick-screen-prompt.md` replaces them whole.

## What gets stored

`judgments` rows, one per `(url, judged_by)`:

| Column | Notes |
|--------|-------|
| `verdict` | `no`, `weak`, `fair`, `strong` (`jj.prompts.VERDICTS`) |
| `reasoning` | the model's sentence, or yours |
| `judged_by` | `user` or `model-quick`; a person's verdict wins. (`model-full` is reserved for a later mirror of full scores.) |
| `model`, `prompt_version` | provenance; `PROMPT_VERSION` is bumped by hand when prompt text changes |
| `listing_id`, `application_id`, `title`, `company` | joins and display |

A listing with a `model-quick` or `user` verdict is never sent again. A person's verdict via `jj judgments put` outranks the model's and removes the posting from later screening and scoring. Full scores still record their result in the `"Fit:"` notes prefix as before.

Prospects: a kept listing (at or above `--keep`, default `fair`) with no application row gets one with notes `Title Fit: N. Quick screen: <verdict>. <reasoning>`. An existing title-only prospect gets the screen note appended. A listing whose company-plus-title fuzzy-matches a *different* url is reported as `duplicate_of_other_url` rather than merged into that record. Full-scored rows are left alone.

## Reading the summary

The first line is always coverage as an unreduced fraction, then verdict counts, then what was missing:

```
3/3 candidate listings were screened (1 batch(es), 0 failed, model haiku)
verdicts: strong 1, fair 0, weak 0, no 2; kept 1 at or above 'fair'
prospects: created 1, annotated 0, already full-scored 0
3 profile document(s) were sent: constraints, preferences, profile
  no background document is stored, so the model screened on the corpus excerpt and profile only
```

`scan-apis` now reports the same way for companies: `148/175 companies returned at least one job`, then each zero-yield company with a reason (`HTTP 404: slug likely wrong`, `empty board`, `no slug in careers_url`, `request failed: ...`).

## Config

```yaml
monitor:
  quick_screen:
    model: haiku        # --model overrides
    batch_size: 50      # max 100
```

Launcher: `scripts/monitor-launcher.sh` passes `--quick-screen --screen-limit ${JJ_SCREEN_LIMIT:-100}`; `JJ_QUICK_SCREEN=0` skips it.

## Known limits of this first cut

- The `"Title Fit:"` / `"Fit:"` notes prefix is still what `get_unscored_selected_prospects` and apply-ready use to tell a title-only prospect from a full-scored one. The judgments table is the real state for screening; retiring the prefix everywhere is a follow-up.
- The screen never sees the description, so a clearance or degree requirement written only there cannot be caught here. That is what the full score is for.
- `--json` exists on the new commands only; the rest of `jj` still prints Rich tables.
- Skills (`/monitor`, `/swarm`, `/pipeline`) do not yet call the quick screen; the launcher and `scan-apis` do.
- Only `job_listings` rows are screened. VC-board jobs land in `investor_board_jobs` and still go through the title gate only.
- Without `--since`, the screen uses `config monitor.score_new_since` like `score-new` does, so the pre-existing backlog is not screened by the scheduled run. Pass `--since ""` (or `--since 2026-01-01`) to reach into it deliberately.
