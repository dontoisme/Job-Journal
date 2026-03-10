# /jobs - Job Search & Scoring

Search for jobs and score them against your professional corpus.

## Usage

```
/jobs                                    # Default: search based on profile
/jobs senior product manager             # Custom search term
/jobs --remote staff pm                  # Remote jobs only
/jobs --salary 180000 director product   # Minimum salary $180k
/jobs score                              # Score saved prospects against your corpus
```

## Workflow

When the user invokes `/jobs`, follow these steps:

### Step 1: Parse Search Criteria

Extract from user input (or use defaults from profile.yaml):
- **Search term:** Default from `profile.yaml` current_title or "product manager"
- **Location:** Default from `profile.yaml` location
- **Remote:** Default false
- **Minimum salary:** Default 0 (no filter)
- **Hours old:** Default 72 (last 3 days)

### Step 2: Run the Search

Use web search to find relevant job postings:

```
Search: "[SEARCH_TERM] jobs [LOCATION] site:greenhouse.io OR site:lever.co OR site:ashbyhq.com"
```

Alternative aggregator searches:
- Indeed: `[SEARCH_TERM] jobs [LOCATION]`
- LinkedIn: `[SEARCH_TERM] jobs [LOCATION]`
- Glassdoor: `[SEARCH_TERM] jobs [LOCATION]`

### Step 3: Present Results

Show the user a formatted table of results:

| # | Company | Role | Location | Salary | Source |
|---|---------|------|----------|--------|--------|
| 1 | Figma | Sr PM, Growth | Remote | $180k-$250k | Greenhouse |
| 2 | Stripe | PM, Developer Tools | SF/Remote | $190k-$270k | Lever |

### Step 4: Offer Next Steps

After showing results, offer:

```
Found X jobs. What would you like to do?

1. **Score all jobs** - I'll fetch each JD and rate fit against your corpus
2. **View a specific job** - Give me the number or company name
3. **Apply to a job** - /apply <url>
4. **Save to prospects** - Add to your prospects list
5. **Refine search** - Add filters (remote, salary, location)
```

---

## Scoring Mode: `/jobs score`

When user says "score" or "score all jobs":

### Scoring Process

1. Read user's corpus from `~/.job-journal/corpus.md`
2. Read prospects from `~/.job-journal/prospects.csv` if exists
3. For each job (up to 20 at a time to manage context):
   a. Fetch the full JD using WebFetch on the job URL
   b. Score fit (0-100%) based on:
      - **Requirements match** (years exp, skills, industry)
      - **Seniority alignment** (title level vs experience)
      - **Domain fit** (tags in corpus: AI, health-tech, growth, etc.)
   c. Assign a recommendation: Strong Fit / Good Fit / Stretch / Skip
4. Present scored results sorted by fit score

### Scoring Output Format

```
## Job Scoring Results

| # | Score | Company | Role | Salary | Recommendation |
|---|-------|---------|------|--------|----------------|
| 1 | 85% | Zillow | Sr PM, Agentic AI | $152k-$257k | **Strong Fit** |
| 2 | 78% | Apollo.io | Sr PM, Inbound | $187k-$250k | Good Fit |
| 3 | 72% | Unity | Principal PM | $179k-$269k | Good Fit |
| 4 | 45% | Netflix | Games PM | $190k-$300k | Stretch |

### Top Recommendations

**#1 Zillow - Senior PM, Agentic AI** (85%)
- Strong: AI/ML experience, agentic systems, orchestration
- Gap: Gaming industry (but transferable)
- URL: [Apply →](url)

**#2 Apollo.io - Senior PM, Inbound** (78%)
- Strong: Growth PM, PLG, B2B SaaS
- Gap: None significant
- URL: [Apply →](url)
```

### After Scoring

Ask the user:
```
Which jobs would you like to apply to?
- Give me numbers (e.g., "1, 2, 5")
- Or say "apply to all Strong Fit"
- Or "save" to add to prospects
- Or "skip" to exit
```

---

## Prospects Management

### Saving to Prospects

When user wants to save jobs for later:

```bash
# Append to prospects.csv
echo "company,role,location,salary_range,url,ats,fit_score,notes,date_applied" >> ~/.job-journal/prospects.csv
```

### Viewing Prospects

```
/jobs prospects
```

Shows saved prospects with their fit scores and application status.

### Top Prospects

```
/jobs top
```

Shows highest-scoring prospects that haven't been applied to yet.

---

## Fit Scoring Criteria

### Domain Tags (from corpus)

| Tag | Keywords to Match |
|-----|-------------------|
| ai | AI, ML, machine learning, LLM, agents |
| growth | PLG, experimentation, activation, retention |
| health-tech | Healthcare, EHR, HIPAA, clinical |
| platform | API, infrastructure, developer tools |
| consumer | B2C, marketplace, e-commerce |
| leadership | Director, VP, Head of, strategy |

### Scoring Rubric

| Category | Weight | Criteria |
|----------|--------|----------|
| Skills Match | 35% | Required skills present in corpus |
| Experience Level | 25% | Years and seniority alignment |
| Domain Fit | 25% | Industry/domain tag overlap |
| Location/Remote | 15% | Location preference match |

### Score Thresholds

| Score | Label | Action |
|-------|-------|--------|
| 80-100% | Strong Fit | Prioritize application |
| 65-79% | Good Fit | Worth applying |
| 50-64% | Moderate Fit | Consider carefully |
| <50% | Stretch/Skip | Low priority |

---

## Search Options

| Option | Flag | Example |
|--------|------|---------|
| Search term | (positional) | `/jobs staff product manager` |
| Remote only | `--remote` | `/jobs --remote` |
| Min salary | `--salary N` | `/jobs --salary 175000` |
| Location | `--location "City, ST"` | `/jobs --location "San Francisco, CA"` |
| Score mode | `score` | `/jobs score` |
| View prospects | `prospects` | `/jobs prospects` |
| Top prospects | `top` | `/jobs top` |

## Examples

```
/jobs
# → Searches based on profile defaults

/jobs --remote senior pm ai
# → Remote jobs matching "senior pm ai"

/jobs --salary 200000 --location "New York, NY" director product
# → Director-level roles in NYC, $200k+ minimum

/jobs score
# → Score jobs from last search against your corpus

/jobs prospects
# → View saved prospects list

/jobs top
# → Show top unappied prospects
```

## Data Files

| File | Purpose |
|------|---------|
| `~/.job-journal/prospects.csv` | Saved job prospects |
| `~/.job-journal/journal.db` | Database with applications table |
| `~/.job-journal/corpus.md` | Professional corpus for scoring |
| `~/.job-journal/profile.yaml` | Default search location/preferences |

## Notes

- **Scoring uses your corpus** — the more complete your corpus, the better scoring works
- **Run `/interview` first** — build your corpus before relying on fit scores
- **Save interesting jobs** — even if you're not ready to apply, save to prospects
- **Salary data** is only available for ~30% of postings
- **Focus on Greenhouse/Lever/Ashby** — these ATS platforms have the best job data
