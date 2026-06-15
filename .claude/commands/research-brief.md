# /research-brief - Why-Now + Why-Me Application Research

Produce a cited, decision-grade research brief for a high-value target role:
**what in recent times is creating demand for this role at this company, and
why is Don worth a conversation.** The brief is a reusable input — it powers
the resume summary's *angle*, the cover letter, the "why {company}?" screening
answer (drafted by `/apply-assist`), and interview prep. One research pass,
four outputs.

This is a per-JD, high-value-target step (e.g. fit >= 80 + target company),
NOT an archetype add-on and NOT part of base resume generation.

## Usage

```
/research-brief <job_url>
/research-brief --id <application_id>
```

## Inputs to gather first

0. **Resolve the application.** If invoked with `--id <application_id>`, load
   the record first to get its `job_url` and confirm the target for persistence
   (`get_application(app_id)` from `jj.db`). If invoked with a bare URL, look up
   the matching application by `job_url` so you have an id to persist to. Hold
   onto the `app_id` — persisting at the end is mandatory when an id exists.
1. **The JD.** WebFetch the URL (fall back to browser/paste). Capture the real
   responsibilities, must-haves, and the team/org it sits in.
2. **Don's evidence.** Read `~/.job-journal/corpus.md` (roles, bullets, metrics)
   and `~/.job-journal/profile.yaml` (summaries, earlier roles). The brief's
   "why me" must trace to these — no invented experience.

## Research (use a sub-agent; cite everything)

Run focused web research (WebSearch + WebFetch). Every demand-driver claim
gets a dated source URL. Target signals:

- **Company/role demand drivers (recent):** product launches, funding, earnings
  commentary, reorgs, new exec hires, strategic pivots, regulatory/market
  shifts, public roadmap statements — anything in the last ~6-12 months that
  explains *why this role exists now*.
- **Team/function context:** what this org owns, who it reports to, recent
  public statements about its priorities.
- **Market/trend tailwinds** the role rides (e.g. agentic products, monetization
  pushes, enterprise GTM) that Don's track record speaks to.

Stop when you can answer "why now" with 2-4 sourced drivers. Do not pad.

## Output — structured brief

```
ROLE: <title> @ <company>   | fit angle: <one line>

WHY NOW (demand drivers)
- <driver> — <one line of why it creates this need>  [source: <url>, <date>]
- ... (2-4, each cited)

WHY DON (connection points — each ties a driver to corpus evidence)
- <driver> -> <Don's specific, corpus-traceable experience/metric>
- ... (2-4)

SUMMARY ANGLE
- Which of Don's strengths to LEAD with for this role (one sentence). This
  selects emphasis; it does NOT add company news to the resume summary.

WHY {COMPANY} (screening answer, ~3-4 sentences, ready for /apply-assist)
- Grounded in a real driver + a real Don credential. No flattery, no invented
  facts, no em-dashes, no banned phrases.

INTERVIEW TALKING POINTS
- 2-3 points connecting Don's experience to the role's actual challenges.

CONFIDENCE & GAPS
- Note any driver that's inference vs. sourced fact, and anything to verify.
```

## Guardrails (non-negotiable)

- **Cited + verifiable.** Every demand-driver claim carries a dated source URL.
  If you can't source it, label it inference — never assert it as fact. A
  confidently wrong company fact on a senior application is a credibility killer.
- **Don's facts stay corpus-grounded.** "Why me" connection points must trace
  to `corpus.md`/`profile.yaml`. No invented metrics, roles, or scope.
- **No company news in the resume summary.** The brief informs the summary's
  *angle* (emphasis), not its content. Company specifics live in the cover
  letter, why-us answer, and interview prep.
- **Resume conventions apply** to any drafted prose: no em-dashes, none of the
  banned phrases ("12+ years," "proven track record," "results-driven,"
  "passionate," "deep experience in").
- **Human-verified before use.** The brief is a draft for Don's review; nothing
  reaches an application until he has eyeballed the sourced claims.

## Persisting

When an application id is known (always, if invoked with `--id` or the URL
matched a tracker record), you MUST store the brief on the record so
`/apply-assist` and interview prep reuse it without re-researching. This is the
last required step, not optional:

```python
from jj.db import update_application
update_application(app_id, research_brief=brief_text)
```

`/apply-assist` checks `applications.research_brief` first and only regenerates
when it is empty.
