# Job Journal vs. Pinloop CLI — Deep Dive Comparison

> **Date:** 2026-09-06
> **Context:** [pinloop-ai/pinloop-cli](https://github.com/pinloop-ai/pinloop-cli) (v0.4.0, MIT, TypeScript, ~9,300 lines) is "a job search tool built for your coding agent to run from a terminal." It is the open-source client half of a hosted product: a large hourly-refreshed corpus of postings, a per-account profile of documents, and an LLM judge that grades postings against that profile. This document compares it with Job Journal (`jj`) at the current `main`, identifies what each does well and poorly, and ranks what Job Journal should adopt. Read alongside [comparison-interview-coach-skill.md](comparison-interview-coach-skill.md), which uses the same structure.

---

## TL;DR

Pinloop and Job Journal overlap on exactly two lifecycle stages: **finding postings** and **deciding which are worth time**. Everything else is disjoint. Pinloop stops where the application starts (it says so in its own guide: "It does not fill application forms in and it does not submit applications"). Job Journal's centre of gravity is everything after that: corpus, resume generation with an integrity audit, application tracking, Gmail pairing, TWC compliance, Slack, analytics.

Where Pinloop is clearly ahead is not features but **contract discipline for an agent-driven CLI**: a machine-readable output shape on every command, stdout/stderr separation so commands pipe, a four-word verdict scale with stored reasoning that is reused instead of re-bought, a cheap batch "quick screen" tier ahead of the expensive full judge, coverage fractions and per-item drop reasons on every report, a spend-confirmation token before any run that costs money, and self-describing instructions generated from the real command tree. Most of that is adoptable into `jj` without adopting Pinloop's hosted model, and several items directly address problems Job Journal has already documented for itself (the 15-spawn daily cap, the `"Fit:"` string-prefix state machine, silent zero-yield ATS slugs, and seven prose copies of the fit rubric).

The single highest-leverage move is to treat Pinloop as a **discovery source**: `pinloop search --json` gives Job Journal a corpus of tens of thousands of postings that its 175 seeded companies and 33 VC boards cannot match, and the adapter is small.

---

## 1. Architecture Comparison

| Dimension | Job Journal | Pinloop CLI |
|-----------|------------|-------------|
| **Type** | Python CLI (Typer) + FastAPI dashboard + 22 Claude Code skills | TypeScript CLI (Commander) over a hosted HTTPS API |
| **Where the work happens** | Locally: SQLite, Claude Code skills, LaunchAgents | On Pinloop's servers; the CLI holds no SQL and no model key |
| **Data ownership** | `~/.job-journal/` (DB, corpus, resumes, tokens) | Account on `api.pinloop.ai`; only a login pass on disk (`~/.pinloop/credentials.json`, mode 0600) |
| **Posting corpus** | Built by the user: 175 seeded companies (`target_companies_data.py`), 33 VC boards, geo search, Greenhouse seeker search | Provided: "large collection" refreshed ~hourly (worked example shows 59,124 postings in one searched set) |
| **Search** | Public ATS JSON APIs, WebFetch scraping, WebSearch site: queries | Keyword search with plural/synonym widening, structured filters, semantic search (`voyage-4` embeddings) with `--from-profile` |
| **Fit judgment** | LLM via `claude -p` spawns; rubric lives in skill prose | Server-side model call (`claude-sonnet-5` in examples); prompt shipped in code and user-overridable |
| **Verdict shape** | 0-100 score + verdict band, breakdown in `evaluation_reports` | One of four words (`no`/`weak`/`fair`/`strong`) + reasoning, stored per posting per account |
| **Automation** | macOS LaunchAgents (currently all disabled, see `services.md`) | Server-side `schedule` (every N hours) and `watch` (hourly, new arrivals only), paid tier |
| **Agent interface** | Slash-command skills that embed Python snippets calling `jj.db` directly | `welcome` / `skill` / `guide` printed text; agent types commands and pipes `--json` |
| **Application stage** | Browser-assisted autofill, staged PDF, screening answers, status lifecycle, email pairing, TWC | None by design |
| **Cost model** | User's Claude Code subscription; internal daily caps | Free tier (25 full judgments/month) or $20/month Pro (400 full or 5,000+ quick) |
| **Tests** | 2 files, ~250 lines | Not in the published repo (source comments reference an extensive suite in the private monorepo) |

**Key insight:** Pinloop is a *service with a CLI*; Job Journal is a *workbench with a CLI*. Pinloop's constraints (no server code in the package, no numbers hardcoded that the server owns, every command documented or the build fails) exist because it ships to strangers. Job Journal's looseness exists because it ships to one person. That difference explains almost every gap below.

---

## 2. Feature Coverage Matrix

### Job Search Lifecycle Stages

| Stage | Job Journal | Pinloop | Gap Owner |
|-------|------------|---------|-----------|
| **Corpus of postings** | Self-built, ~200 sources, API + scrape | Hosted, tens of thousands, hourly refresh | Pinloop stronger |
| **Keyword search** | WebSearch `site:` queries in `/jobs`; Greenhouse seeker search via HAR auth | First-class, with match report on stderr | Pinloop stronger |
| **Semantic search** | Reserved (`[rag]` extra, `jj index` referenced but absent) | `search --semantic --from-profile` | Pinloop only |
| **Structured filters** | Title regex + foreign-marker denylist (`score_title_fit`) | `--country`, `--workplace`, `--employment`, `--posted-after`, offline `filter` verb | Pinloop stronger |
| **Cheap pre-screen** | Deterministic title scorer (0 LLM cost) | LLM quick screen, 100 postings/call, 1/14th cost of a full judge | Different; both valuable |
| **Full fit judgment** | 4-category 100-point rubric, comp research, STAR stories, evaluation report | 4-word verdict + reasoning, constraints hard-veto | JJ richer, Pinloop cleaner |
| **Verdict reuse** | Dedup by URL; re-scoring is manual | Stored verdict read back free; `--again` to override; `--unjudged` filter | Pinloop stronger |
| **Human verdicts** | Slack [Pass] button, `skipped` status | `judgment put --verdict --reasoning`, marked `judged-by user` | Pinloop stronger |
| **Profile / self-description** | `profile.yaml`, `corpus.md`, `archetypes.yaml`, `voice_profile.md` | Named documents with 7 reserved names, 64 KB each, PDF resume | JJ richer, Pinloop more structured |
| **Company monitoring** | Target companies + VC boards, delta detection in `job_listings` | `watch` over a stored routine (new arrivals only) | Both; JJ per-company, Pinloop per-query |
| **Saved pipelines** | Skills (prose, 300-700 lines each) | `routine put` as validated JSON step lists, run server-side | Pinloop stronger as data; JJ far more capable |
| **Scheduling** | LaunchAgents, macOS only, currently off | Server-side, cross-platform, paid | Pinloop stronger |
| **Shortlists** | Application statuses, `is_target` | `tab` named lists (100 tabs x 1,000 postings) | Roughly equal |
| **Resume generation** | Full: corpus select, Google Docs, matched format, `_pre_export_audit` | None | JJ only |
| **Application autofill** | `/apply-assist` with Chrome MCP, hard stop before Submit | None ("application-instructions" reserved name hints at a planned fill engine) | JJ only |
| **Cover letters / research briefs** | `/cover-letter`, `/research-brief` persisted to DB | None | JJ only |
| **Status tracking** | 12 statuses, event audit trail, `transition_application_status` | None | JJ only |
| **Email intelligence** | Gmail pairing, ATS domain patterns, resolution classification | None | JJ only |
| **Compliance (TWC)** | Full: weeks, claim periods, payment requests, print view | None | JJ only |
| **Notifications** | Slack Block Kit with action buttons, daily digest | None (results wait in tabs / `routine results`) | JJ only |
| **Analytics** | Funnel, time-in-stage, rejection patterns, fit-score correlation | None | JJ only |
| **Feedback channel** | GitHub issues | `pinloop message` to the builder, 20/day | Pinloop only |

### Overlap Analysis

Only three rows are genuinely contested: corpus, search, and the judge. In all three Pinloop's advantage is infrastructure Job Journal should not rebuild (a hosted corpus, an embedding index) plus design decisions Job Journal *can* copy (verdict scale, reuse, quick tier, filters as data).

---

## 3. What Pinloop Does Well

### 3.1 The `--json` pipe contract

Every command that returns rows prints exactly one JSON object on stdout with `rows` and an optional `cursor`. Anything a human needs but the next command must not swallow (the search report, drop reasons, warnings, refusals, progress) goes to stderr. Commands compose:

```
pinloop search backend intern --posted-after 2026-07-01 --json \
  | pinloop judge --keep strong --json \
  | pinloop tab add strong-2027
```

Job Journal has **zero `--json` flags** in `jj/cli.py`. Skills get structured data by embedding Python that imports `jj.db` and calls functions directly (`/score` has five such blocks; `/monitor` has 21). That couples every skill to internal function signatures and makes the CLI unusable by any agent that is not Claude Code reading the skill file.

### 3.2 A verdict scale, not a score

Four ordered words (`no` < `weak` < `fair` < `strong`), defined once in `src/shared/verdicts.ts`, used by the model's allowed answers, by `--keep`, by `judgment list --verdict`, and by the printed drop reason ("judged weak, below strong"). The reasoning is stored with the verdict and is written *for the person to read*. `constraints` produce a deterministic `no` with the broken rule named.

Job Journal's 0-100 score is more granular but less honest: the bands (80/65/50) differ between `/apply` and every other skill, the rubric text is duplicated in seven skill files, and the verdict is derived from the score rather than being the model's own word.

### 3.3 Two-tier judging with explicit cost ratios

`judge --quick` sends up to 100 postings per call with no description text and stores a lighter verdict; a full `judge` reads the whole posting. The guide states the ratio (one quick screen costs 1/14th of one full judgment) and tells the agent the intended pattern: screen wide, judge the survivors. A full judge overwrites a quick verdict and says so.

Job Journal's `score_title_fit` is the deterministic equivalent of the quick tier and costs nothing, but there is no LLM batch tier between it and the 900-second `claude -p "/slack-apply <url>"` spawn. That is why `scoring.py` needs a hard 15/day ceiling.

### 3.4 Coverage fractions and drop reasons everywhere

"Andrew's rule, 2026-08-15": whenever the product says something was left out, the first thing it says is how much came through, as an unreduced fraction (`996/1000 postings had embeddings and were considered`), then which ones and why. `filter` guarantees every input row comes back exactly once, as a survivor or in the drop list with the rule that dropped it. Routine runs report per step: "step 2 (judge): 1/3 postings handed in came out".

Job Journal's monitor writes `companies_checked` and `new_listings_found` but nothing distinguishes "returned 0 jobs because the board is empty" from "returned 0 because the slug is wrong". `target_companies_data.py` explicitly shrugs at this ("If a slug is wrong, the scanner returns 0 jobs, no harm done").

### 3.5 Spend confirmation tokens

Any command that would call a model (`judge`, `routine run`, `routine put`, `schedule put`, `watch put` when a judge step is reachable) takes two calls. The first does nothing but print what would run, how many judgments it costs, how many are left this month, and a one-hour token bound to that exact request. The agent is instructed to put the choice to the person in one sentence and to mention the free alternative (read the postings yourself, store your own opinion with `judgment put`). The comment in `guide-text.ts` records why: an agent judged a hundred postings on the builder's own account without saying anything.

Job Journal has the same failure mode (autonomous skills spawning Sonnet runs) and handles it with caps rather than consent.

### 3.6 Self-describing, version-stamped instructions

`pinloop welcome` prints a short SKILL.md (agentskills.io format, works in Claude Code, Codex, Cursor, Gemini CLI, Copilot) that deliberately names only two commands and ends with "run `pinloop guide --skill <version>`". `pinloop guide` is generated by walking the live Commander tree and looking up prose per command; a command with no prose fails the test suite. Limits printed in the guide are imported from the same constants the server enforces, never retyped. A stale saved skill file triggers a notice at the top of the guide.

Job Journal's `CLAUDE.md` says 16 tables and 9 skills; the repo has 24 and 22. `docs/daily-workflow.md` references `/hunt`, `/track`, `/resume-workflow` and `/prospects`, none of which exist. `/greenhouse` documents `poll --score` and `jj index`, neither of which exist.

### 3.7 Profile as named documents with reserved semantics

Seven reserved names, each with fixed meaning: `resume` (PDF), `background`, `preferences`, `constraints` (hard veto), `application-instructions`, `judge-prompt`, `quick-judge-prompt` (override the shipped prompts wholesale). Any other lowercase-dash name is the user's to keep. The judge report names every missing reserved document and what the model therefore could not do ("no constraints document is stored, so nothing could rule a posting out on its own").

### 3.8 Routines, schedules, watches as data

A routine is a JSON list of up to 20 steps drawn from six posting-in/posting-out verbs. Arguments are validated at store time against each verb's real signature, so a typo is caught once rather than every night. A `schedule` fires every N hours; a `watch` fires hourly over only postings that arrived since it last looked and does nothing when nothing arrived. Both keep last-run outcomes. Cancelling a subscription pauses them but deletes nothing.

### 3.9 Honest terminal behaviour

Progress redraws in place on stderr only when stderr is a TTY; a pipe or an agent's captured output gets plain lines. `NO_COLOR` drops to the same plain output. `tab get` shows postings as they are now and marks removed ones as gone rather than silently dropping them. Fixed-vocabulary options (`--workplace`, `--employment`) refuse bad values with the list of good ones; the guide even warns that `--country CA` silently matches nothing.

---

## 4. What Job Journal Does Well

### 4.1 The corpus and "SELECT, don't COMPOSE"

Pinloop has no concept of the candidate's own bullets. Job Journal's `roles` → `entries` → `skills` model, `validate_bullets` with drift scoring, `resume_import.py` back-filling unmatched bullets into `corpus_suggestions`, and the `stories` STAR+R bank are a different category of asset. `_pre_export_audit()` in `google_docs.py` is a fail-closed integrity gate in code, not prose.

### 4.2 Resume generation pipeline

Disciplined / strict / freeform modes, five keyword-matched variants, four pre-built archetypes, the matched format (`split_roles_by_window`, `build_matched_skills`, `order_bullets_for_story`), Google Docs generation and PDF export, and an evaluation agent with over-tailoring deductions. Pinloop's `resume` document is an opaque PDF the model reads.

### 4.3 Discovery breadth per source

Pinloop's corpus is wide but generic. Job Journal has custom adapters for Amazon and Netflix (which have no public ATS API), ATS-type probing for VC portfolio boards on custom domains, Google Maps geo discovery over Austin corridors, and the `my.greenhouse.io` seeker search. Delta detection in `job_listings` (`record_job_listing`, `mark_stale_listings`) is per company and per URL.

### 4.4 Everything after "worth applying"

`/research-brief` (cited why-now / why-me persisted to `applications.research_brief`), `/apply-assist` (Chrome MCP form reading and filling, staged PDF attach, voice-matched screening answers, hard stop before Submit, writing samples harvested back into `writing_samples.jsonl`), `/cover-letter`, evaluation reports with comp research, Slack [Go]/[Applied]/[Pass]/[Stage resume] buttons. None of this exists in Pinloop and Pinloop says it never will.

### 4.5 Tracking, email, compliance, analytics

Twelve-state lifecycle with an `events` audit trail; read-only Gmail OAuth pairing with ATS-domain patterns and four-bucket resolution classification; TWC week/claim-period/payment-request modelling with a print view; a funnel built from four evidence sources (`_FUNNEL_EVIDENCE_SQL`). This is the operations engine Pinloop deliberately does not have.

### 4.6 Local-first and free

No account, no monthly allowance, no server that can disappear. The whole system reads and writes human-editable files under `~/.job-journal/`.

---

## 5. What Each Could Do Better

### 5.1 Pinloop

| Weakness | Detail |
|----------|--------|
| **Stops at the verdict** | No tracking, no resume, no application. A `strong` verdict lands in a tab and the user is on their own. |
| **Hosted only, single builder** | Everything except `filter` needs the server. `pinloop message` routes to one person. If the service pauses, the CLI is inert and the profile, verdicts, tabs and routines are inaccessible. |
| **Paid gate on automation** | `schedule` and `watch` require Pro. A free account cannot run anything unattended. |
| **Instruction cost per session** | `guide-text.ts` is 973 lines and the welcome flow tells the agent to read all of it before running anything. That is real context spend every conversation, and the skill file's own design (name nothing so it never goes stale) forces it. |
| **Filters are thin** | One `--country` per run, full name only, no region ("keeping the postings in Europe means naming the countries yourself and running filter once per country"). No salary, no title-seniority, no company-size filter. |
| **Quick screen is blind to descriptions** | Stated plainly in the guide: clearance or degree requirements in the description cannot be caught by `--quick`. |
| **No cross-source dedup visible** | Postings carry `external_id` and company ids, but nothing in the CLI reports whether the same role appears on two boards. |
| **Verdict provenance is lossy** | A typed judge run and a scheduled one both land under `judged-by pinloop` "and cannot be told apart." |
| **Unshipped hints in the contract** | `application-instructions` is reserved for a "fill engine" that does not exist in the published client. |

### 5.2 Job Journal

| Weakness | Detail | Pinloop's answer |
|----------|--------|------------------|
| **No machine-readable CLI output** | Zero `--json` flags; skills embed `from jj.db import ...` snippets | `--json` on every row-returning command, stderr for prose |
| **Rubric lives in prose, seven times** | Skills Match 35 / Experience 25 / Domain 25 / Location 15, with inconsistent bands between `/apply` and the rest | One `DEFAULT_JUDGE_PROMPT` constant, user-overridable by name |
| **Scoring state encoded in a string prefix** | `notes.startswith("Fit:")` vs `"Title Fit:"` decides whether an app is "really scored" (`scoring.py:355`, `db.py:1805`, two skills) | A `judgments` row with `verdict` and `judged_by` |
| **No cheap LLM tier** | Title regex, then a 900-second per-URL spawn; hence the 15/day cap | Batched quick screen at 1/14th cost |
| **Silent zero-yield sources** | Wrong ATS slugs return 0 jobs indistinguishably from empty boards | Coverage fractions and named drops on every report |
| **Spend without consent** | `/monitor` and `/swarm` generate resumes and spawn Sonnet runs autonomously; caps are the only brake | Two-call confirmation token with the count of remaining allowance |
| **Docs and code disagree** | 16 vs 24 tables, 9 vs 22 skills, phantom commands (`/hunt`, `jj index`, `poll --score`), self-contradicting resume cap in `/monitor` | Guide generated from the command tree; undocumented command fails the build |
| **Single-agent, single-platform** | Skills only work inside Claude Code; scheduling only on macOS via `launchctl`; `textutil` for docx; personal data (`SpareFoot`/`IBM` blocklist, Austin corridors, TWC epoch, name fallback) hardcoded in library code | SKILL.md works in ~40 agent tools; server-side scheduling |
| **Minimal tests** | No tests for `score_title_fit`, `_pre_export_audit`, scanners, email classification, TWC date math; `start-today.md` has a month-boundary bug | (private, but the package boundary, guide coverage, and skill-file rules are all test-enforced per source comments) |
| **Automation is switched off** | All five LaunchAgents disabled since 2026-08-18 (`services.md`) | Watches and schedules keep firing server-side |
| **Discovery ceiling** | 175 seeded companies + 33 VC boards; corpus grows only when the user adds sources | Hourly-refreshed corpus of tens of thousands |

---

## 6. What Job Journal Should Adopt

Ordered by leverage. Each item names the Pinloop pattern, the Job Journal surface it lands on, and the problem it fixes.

### 6.1 Pinloop as a discovery source (High Impact, Low Effort)

**What:** An adapter in `jj/ats_scanner.py` (or a new `jj/sources/pinloop.py`) that shells out to `pinloop search ... --json` / `pinloop list --posted-after ... --json` when the binary and a login are present, maps `rows` into `record_job_listing()` with a synthetic `company_id` per Pinloop `company_id`, and feeds the existing `score_title_fit` pre-filter. Expose as `jj monitor scan-pinloop --query "senior product manager" --posted-after <last run>`.

**Why it matters:** This is the one thing Job Journal cannot build for itself cheaply. Pinloop's free tier gives keyword search, filtering and `list` at no cost; only judging and semantic search are metered. Job Journal keeps its own scoring, resume and tracking on top. Dedup falls out of the existing `UNIQUE(company_id, url)` and `is_known_job()`.

### 6.2 `--json` on the CLI, stderr for prose (High Impact, Medium Effort)

**What:** Add `--json` to every `jj` command that returns rows (`app status`, `corpus list/search`, `monitor` listings, `resume list`, `greenhouse poll`, `email pair`), printing one object with `rows` (+ `cursor` where paging exists) to stdout and routing all Rich output to stderr when the flag is set. Then migrate the inline `from jj.db import ...` blocks in skills to `jj ... --json` calls, starting with `/score` and `/slack-apply`.

**Why it matters:** Decouples 22 skills from `jj.db` function signatures, makes `jj` usable from Codex/Cursor/shell pipelines, and is the precondition for 6.6. Pinloop's rule that prose never goes to stdout is the part to copy exactly.

### 6.3 A verdict scale with stored reasoning and reuse (High Impact, Medium Effort)

**What:** A `judgments` table (`application_id` or `job_listing_id`, `verdict` in `no|weak|fair|strong`, `reasoning`, `judged_by` in `user|model-quick|model-full`, `model`, `prompt_version`, `created_at`). Scoring skills write a verdict word alongside the numeric score; the numeric bands map onto the four words in one place (`jj/scoring.py`). `score_new_prospects` skips anything with a stored verdict unless `--again`. Slack [Pass] writes `judged_by=user, verdict=no`. Add `jj app judge <id> --verdict fair --reasoning "..."` for verdicts made by hand.

**Why it matters:** Retires the `"Fit:"`/`"Title Fit:"` string-prefix state machine, gives analytics a human-vs-model comparison (`get_fit_score_analysis` can finally answer whether the model's `strong` correlates with interviews), and makes re-scoring idempotent.

### 6.4 A batched quick-screen tier (High Impact, Medium Effort)

**What:** Between `score_title_fit` and the full per-URL spawn, add one `claude -p` call that receives up to 50-100 new listings as plain facts (title, company, location, salary if present, posted date) plus `constraints.md` and `preferences.md` (see 6.5), and returns one verdict word and one sentence per listing. Only `fair`/`strong` proceed to the 900-second full score. Store as `judged_by=model-quick`.

**Why it matters:** The 15/day ceiling in `scoring.py` exists because every score is a full JD fetch plus a long Sonnet run. Pinloop's measured ratio is 14:1. Screening 100 listings for the cost of 7 full scores changes what the daily cap means. The title regex stays as the zero-cost first pass.

### 6.5 Reserved profile documents, especially `constraints` (Medium Impact, Low Effort)

**What:** Two new files under `~/.job-journal/`: `constraints.md` (hard rules: no international, no relocation, comp floor, no clearance roles) and `preferences.md` (wants and does-not-wants). `jj/config.py` loads them; every scoring prompt (6.7) injects them with the Pinloop rule verbatim: a broken constraint is `no`, whatever else is true, and the reasoning must name the rule. Scoring output reports which documents were absent.

**Why it matters:** Today the international check is a 24-term denylist inside `score_title_fit` and the comp floor is nowhere. Putting constraints in a document the user edits, and having the model name the rule it applied, is cheaper and more auditable than growing the denylist.

### 6.6 Coverage fractions and named drops in monitor output (Medium Impact, Low Effort)

**What:** `monitor_runs.summary` and the Slack payload state, in this order: `148/175 companies returned a board`, then the list of companies that returned 0 with a reason (`HTTP 404: slug likely wrong`, `empty board`, `timeout`). `score_title_fit` drops are reported as `dropped <title>: role_type 10, below 25` rather than silently not created. `mark_stale_listings` refuses to mark a whole board stale when the fetch returned 0 rows and says so.

**Why it matters:** Directly fixes two documented pain points: unverified seed slugs and the WebFetch-empty-page cascade that re-reports an entire board as new. The Pinloop rule (fraction first, unreduced, then the list) is the part to copy.

### 6.7 One rubric in code, overridable by document (Medium Impact, Low Effort)

**What:** Move the fit rubric and the RJ rubric from seven skill files into `jj/prompts.py` as constants with a `PROMPT_VERSION`, printed by `jj score prompt` and `jj score prompt --rj`. Skills call the command instead of restating the rubric. `~/.job-journal/judge-prompt.md`, when present, replaces the shipped text whole (Pinloop's `judge-prompt` semantics). Record `prompt_version` on every judgment (6.3).

**Why it matters:** Ends the drift between `/apply` (85/70/55/40) and everything else (80/65/50), and makes rubric changes a diff in one file with a version stamp analytics can segment on.

### 6.8 Spend preview before autonomous runs (Medium Impact, Low Effort)

**What:** `jj monitor scan-apis --score-new --preview` prints how many full scores and quick screens would run, the daily allowance remaining (`score-daily-count.json` already tracks it), and exits. Headless skills (`/monitor`, `/swarm`, `/pipeline`) run the preview first and, when the count exceeds a configurable threshold, post to Slack and wait for [Go] rather than proceeding. Interactive skills put the count to the user in one sentence before spawning.

**Why it matters:** Same failure Pinloop hit on 2026-08-26 (an agent judging a hundred postings unasked). Caps limit damage; a preview prevents it and makes the cost legible.

### 6.9 Generated guide and a portable SKILL.md (Medium Impact, Medium Effort)

**What:** `jj guide [command]` walks the Typer app and prints one prose entry per command from a `GUIDE_TEXT` dict; a test fails naming any command without an entry. `jj skill` prints a short agentskills.io SKILL.md that names only `jj guide` and carries a `SKILL_VERSION`; `/start-today` and `/setup` compare the saved version and warn when stale. Limits printed in the guide (daily score cap, resume cap per run, TWC three-per-week) are imported from the constants that enforce them.

**Why it matters:** The documentation drift catalogued in 5.2 is structural, not carelessness: nothing fails when a doc lies. This is also the path to using `jj` from agents other than Claude Code.

### 6.10 Routines as validated data (Low Impact now, Medium Effort)

**What:** A `routines:` block in `config.yaml` where a monitor pipeline is a list of steps over a fixed verb set (`scan`, `filter`, `title-screen`, `quick-screen`, `score`, `notify`), validated on load against each verb's accepted arguments. `jj monitor run <routine>` executes it and reports per-step handed-in/came-out counts.

**Why it matters:** `/monitor`, `/swarm`, `/pipeline` and `/vc-boards` are four prose variants of the same pipeline with different thresholds and parallelism. Once 6.2, 6.4 and 6.6 exist, most of what those skills do is a step list. Defer until then.

---

## 7. What NOT to Build

- **A hosted corpus or embedding index.** Use Pinloop's (6.1) or WebSearch. The `[rag]` extra and the phantom `jj index` should be removed rather than finished.
- **Accounts, billing, allowances.** Job Journal's cost control is the user's own Claude subscription plus caps; that is the right shape for one user.
- **A `message`-to-builder channel.** GitHub issues.
- **Server-side scheduling.** The fix for macOS-only LaunchAgents is a cron/systemd-timer option and `jj monitor run-once` that any scheduler can call, not a service.
- **Pinloop's tabs.** Application statuses plus `is_target` already cover shortlists; a `tabs` table would be a third place to keep the same fact.

---

## 8. Integration Architecture (If Both Tools Are Used)

```
┌─────────────────────────┐        ┌──────────────────────────────────────┐
│  Pinloop (hosted)       │        │  Job Journal (~/.job-journal/)        │
│                         │        │                                      │
│  corpus (hourly)  ──────┼─search─┼─►  job_listings  ──► score_title_fit │
│  --json rows            │        │        │                 │           │
│                         │        │        ▼                 ▼           │
│  profile documents      │◄─put───┼─  constraints.md    quick-screen     │
│   (resume, background,  │        │   preferences.md        │            │
│    constraints)         │        │   corpus.md (excerpt)   ▼            │
│                         │        │                     full score       │
│  judge / judgment ──────┼─json───┼─►  judgments (judged_by=pinloop)     │
│                         │        │        │                             │
│  tab / watch            │        │        ▼                             │
│   (optional, Pro)       │        │  applications ─► resume ─► apply     │
│                         │        │  ─► email pairing ─► TWC ─► analytics│
└─────────────────────────┘        └──────────────────────────────────────┘
```

**Data flows:**
1. Pinloop `search`/`list --json` seeds `job_listings`; Job Journal owns dedup, delta and scoring from there.
2. `constraints.md` and `preferences.md` are pushed to Pinloop with `profile put` so its judge and Job Journal's read the same rules.
3. Pinloop verdicts, when bought, land in `judgments` with `judged_by=pinloop` and skip Job Journal's own scoring unless `--again`.
4. Human verdicts flow the other way: a Slack [Pass] becomes `pinloop judgment put --verdict no` so Pinloop stops surfacing that posting.
5. Everything from resume onward stays local.

Steps 2-4 are optional; step 1 alone captures most of the value at no cost.

---

## 9. Priority Ranking

| Priority | Improvement | Effort | Impact | Rationale |
|----------|------------|--------|--------|-----------|
| **P0** | 6.1 Pinloop as a discovery source | Low | High | Largest corpus gain available; free tier suffices; adapter is ~150 lines |
| **P1** | 6.3 Verdict scale + `judgments` table | Medium | High | Retires the string-prefix state machine; unlocks 6.4 and analytics |
| **P1** | 6.4 Batched quick-screen tier | Medium | High | Turns the 15/day cap from a wall into a budget |
| **P2** | 6.2 `--json` CLI contract | Medium | High | Decouples skills from `jj.db`; precondition for portability |
| **P2** | 6.6 Coverage fractions + named drops | Low | Medium | Fixes two documented monitor failure modes |
| **P2** | 6.7 One rubric in code, versioned | Low | Medium | Ends seven-copy drift; stamps every judgment |
| **P3** | 6.5 `constraints.md` / `preferences.md` | Low | Medium | Replaces the denylist; feeds both judges |
| **P3** | 6.8 Spend preview | Low | Medium | Consent before autonomous spend |
| **P4** | 6.9 Generated guide + SKILL.md | Medium | Medium | Structural fix for doc drift; multi-agent reach |
| **P5** | 6.10 Routines as data | Medium | Low | Wait for P1-P2 to land first |

---

## 10. Implementation status (2026-09-06)

An experimental first cut of the adoption list landed on this branch. See [quick-screen.md](quick-screen.md) for usage.

| Item | Status | Where |
|------|--------|-------|
| 6.1 Pinloop as a discovery source | **Not built.** Held pending a read of Pinloop's terms; see the note below. | |
| 6.2 `--json` CLI contract | Partial: `app status`, `monitor score-new`, `monitor quick-screen`, all `judgments` commands | `jj/cli.py` (`_emit_json`, `err_console`) |
| 6.3 Verdict scale + `judgments` table | Done | `jj/prompts.py`, `jj/db.py` (`record_judgment`, `get_best_judgment`, ...), `jj judgments` |
| 6.4 Batched quick-screen tier | Done | `jj/quick_screen.py`, `jj monitor quick-screen`, `scan-apis --quick-screen`, `score_new_prospects` reads quick verdicts first |
| 6.5 `constraints.md` / `preferences.md` | Done (plus `background.md`); missing documents reported | `jj/prompts.py` (`PROFILE_DOCUMENTS`) |
| 6.6 Coverage fractions + named drops | Done for API scans and the screen | `scan_all_api_companies` summary, `quick_screen_new_listings` |
| 6.7 One rubric in code, versioned, overridable | Done for the quick screen and the fit bands; skills still carry their prose copies | `jj prompts show`, `PROMPT_VERSION`, `~/.job-journal/quick-screen-prompt.md` |
| 6.8 Spend preview | Done | `score-new --preview`, `quick-screen --preview` |
| 6.9 Generated guide + SKILL.md | Not built | |
| 6.10 Routines as data | Not built | |

**On using Pinloop's free tier as a source.** Pinloop's README and its own agent guide say keyword search, `list`, `fetch`, `filter`, tabs and routines are free and unmetered, and the guide explicitly tells agents to use them as "the free way" instead of paying for judgments. A daily `pinloop list --posted-after <yesterday> --json` for a handful of queries is inside that design and well under the stated limits (120 requests a minute, 5,000 postings per command). What would cross a line is mirroring the corpus, redistributing it, or routing around the metered judge and semantic search. The remaining question is the terms of service at pinloop.ai/terms, which this comparison did not read, and the dependency on a one-person service. Building our own wider net instead means more ATS adapters (Workday, SmartRecruiters, iCIMS, Rippling), which is independent work and worth doing either way.

---

## 11. Summary

**Pinloop** is a narrow, well-built service: search a big corpus, judge postings against a profile, keep lists, run it on a schedule. Its published client is small because the product lives on the server, and its real contribution to Job Journal is a set of design rules for agent-driven CLIs that were clearly earned the hard way and are written down in the source: one output shape, prose on stderr, verdicts as words with reasoning kept, cheap screening before expensive judging, fractions before excuses, consent before spend, and instructions that cannot go stale.

**Job Journal** covers the whole lifecycle and owns the parts that matter most to an actual application: the corpus, the resume, the tracking, the compliance. Its weaknesses are the ones a one-person tool accumulates: prose where data should be, documentation that nothing checks, cost controls that are caps rather than consent, and a discovery ceiling set by how many companies one person can seed.

The right relationship is not either/or. Use Pinloop's corpus as a source, copy its contract discipline into `jj`, and keep everything from the verdict onward local. P0 is a small adapter. P1 and P2 are the refactors Job Journal already knew it needed, now with a worked reference for how they should look.

---

*Sources: [pinloop-ai/pinloop-cli](https://github.com/pinloop-ai/pinloop-cli) (commit d305a11, 2026-08-26) — `src/shared/guide-text.ts`, `welcome.ts`, `skill-file.ts`, `registry.ts`, `verdicts.ts`, `coverage.ts`, `filter.ts`, `limits.ts`, `progress-events.ts`, `src/cli/pinloop.ts` | Job Journal `main` — `jj/scoring.py`, `jj/ats_scanner.py`, `jj/db.py`, `jj/google_docs.py`, `.claude/commands/*.md`, `docs/services.md`, `docs/pipeline-architecture-v1-2.md`*
