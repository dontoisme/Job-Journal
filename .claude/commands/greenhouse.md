# /greenhouse - Greenhouse Job Board Poller

Poll my.greenhouse.io for job listings and import them as prospects.

## Usage

```
/greenhouse                              # Poll using saved defaults
/greenhouse setup ~/Downloads/file.har   # Import auth from HAR file
/greenhouse poll                         # Search and display jobs
/greenhouse import                       # Poll and import as prospects
/greenhouse config                       # Show current configuration
```

## Workflow

When the user invokes `/greenhouse`, follow these steps:

### Check Authentication First

Before any operation, check if Greenhouse is configured:

```bash
jj greenhouse config --show
```

If "Configured: No" is shown, guide the user through setup.

---

## Setup Flow: `/greenhouse setup <har_file>`

When user provides a HAR file path:

### Step 1: Verify HAR File Exists

Check that the file exists and is readable.

### Step 2: Import Authentication

```bash
jj greenhouse setup --har <har_file_path>
```

### Step 3: Confirm Success

Show what was extracted:
- CSRF token (truncated)
- Inertia version
- Number of cookies

### Step 4: Prompt for Search Defaults

Ask the user:
```
Authentication saved! Would you like to set up search defaults?

1. **Set defaults now** — I'll ask for your preferred query, location, etc.
2. **Skip for now** — Use defaults later with `jj greenhouse config`
```

If they want to set defaults:

```bash
jj greenhouse config \
  --query "Product Manager" \
  --location "Austin, Texas, United States" \
  --date past_day
```

---

## Poll Flow: `/greenhouse` or `/greenhouse poll`

### Step 1: Check Configuration

```bash
jj greenhouse config --show
```

If not configured, tell the user:
```
Greenhouse not configured. To set up:

1. Export a HAR file from your browser after searching on my.greenhouse.io
2. Run: /greenhouse setup ~/Downloads/my.greenhouse.io.har
```

### Step 2: Run the Search

```bash
jj greenhouse poll
```

Or with custom parameters:
```bash
jj greenhouse poll --query "Senior PM" --date past_week --pages 5
```

### Step 3: Present Results

Show the table of jobs found with:
- Company name
- Position title
- Location
- Fit score (if `--score` was used)

### Step 4: Offer Next Steps

```
Found X jobs. What would you like to do?

1. **Import all** — Add these as prospects to your tracker
2. **Import selected** — Give me the numbers (e.g., "1, 3, 5")
3. **Score jobs** — Re-run with RAG scoring against your corpus
4. **Apply to one** — /apply <url>
5. **Refine search** — Change query, location, or date filter
```

---

## Import Flow: `/greenhouse import`

### Step 1: Poll and Import

```bash
jj greenhouse poll --import
```

### Step 2: Report Results

Show:
- Number imported
- Number skipped (already in database)
- Next steps: "View with `jj stats` or start applying with `/apply`"

---

## Config Flow: `/greenhouse config`

### Show Current Config

```bash
jj greenhouse config --show
```

Present the configuration clearly:
- Search query
- Location
- Coordinates (if set)
- Date filter
- Authentication status

### Update Config

If user wants to change settings:

```bash
jj greenhouse config --query "Staff PM" --location "Remote"
```

---

## HAR Export Instructions

When user needs to create a HAR file, provide these steps:

```
## How to Export a HAR File

1. Open Chrome and go to my.greenhouse.io
2. Log in if needed
3. Open DevTools: Cmd+Opt+I (Mac) or F12 (Windows)
4. Click the **Network** tab
5. Search for jobs (e.g., "Product Manager" in "Austin, TX")
6. Right-click anywhere in the Network panel
7. Select **Save all as HAR with content**
8. Save to your Downloads folder

Then run:
  /greenhouse setup ~/Downloads/my.greenhouse.io.har
```

---

## Scoring Integration

If user has indexed their corpus (`jj index`), offer scoring:

```bash
jj greenhouse poll --score
```

This adds a fit score column (0-100) based on RAG similarity matching.

**If not indexed:**
```
Tip: Run `jj index` to enable job scoring against your professional corpus.
```

---

## Error Handling

| Error | Response |
|-------|----------|
| "Greenhouse not configured" | Guide through HAR setup |
| "Authentication failed" | Session expired — need fresh HAR |
| "No jobs found" | Suggest broader search or remove date filter |
| HAR file not found | Verify path, suggest Downloads folder |
| HAR parse error | Must capture a search request, not just page load |

---

## Full Command Reference

| Command | Description |
|---------|-------------|
| `/greenhouse` | Poll with defaults, show results |
| `/greenhouse setup <har>` | Import auth from HAR file |
| `/greenhouse poll` | Search and display jobs |
| `/greenhouse import` | Poll and import as prospects |
| `/greenhouse config` | Show/edit search configuration |
| `/greenhouse score` | Poll with RAG scoring |

---

## Example Session

```
User: /greenhouse setup ~/Downloads/my.greenhouse.io.har

Claude: Importing authentication from HAR file...

✓ Authentication saved!
  - CSRF Token: abc123def456...
  - Inertia Version: 8f7e6d5c4b3a
  - Cookies: 2 session cookies

Would you like to set search defaults now?

User: Yes, Product Manager in Austin

Claude: Setting defaults...

jj greenhouse config --query "Product Manager" --location "Austin, Texas, United States" --date past_day

✓ Configuration saved! Run `/greenhouse` to search for jobs.

User: /greenhouse

Claude: Searching Greenhouse...

Query: Product Manager
Location: Austin, Texas, United States
Date: past_day

| # | Company | Position | Location |
|---|---------|----------|----------|
| 1 | Acme Corp | Sr PM, Growth | Austin, TX |
| 2 | TechStart | Product Manager | Remote |
| 3 | BigCo | PM, Platform | Austin, TX |

Found 3 jobs. What would you like to do?

1. Import all as prospects
2. Apply to one (/apply <url>)
3. Score against corpus
4. Refine search

User: Import all

Claude: jj greenhouse poll --import

✓ Imported 3 jobs as prospects
  - Skipped: 0 (already in database)

View your prospects with `jj stats` or start applying with `/apply`.
```

---

## Data Files

| File | Purpose |
|------|---------|
| `~/.job-journal/greenhouse_auth.yaml` | Auth credentials |
| `~/.job-journal/config.yaml` | Search defaults under `greenhouse:` |
| `~/.job-journal/journal.db` | Applications table |

## Notes

- Sessions expire after a few hours — re-export HAR if auth fails
- Scoring requires `jj index` to be run first
- Jobs are deduplicated by URL when importing
- Use `--pages 5` to fetch more results (default is 3 pages)
