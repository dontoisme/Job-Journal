# Greenhouse Job Board Integration

Poll my.greenhouse.io for job listings and import them as prospects.

## Overview

The Greenhouse integration allows you to:
- Search for jobs on my.greenhouse.io using their internal API
- Score jobs against your professional corpus (if RAG indexed)
- Import jobs as prospects into your application tracker

## Setup

### Step 1: Export HAR File

1. Open Chrome DevTools (F12 or Cmd+Opt+I)
2. Go to the **Network** tab
3. Visit [my.greenhouse.io](https://my.greenhouse.io) and search for jobs
4. Right-click in the Network panel → **Save all as HAR with content**
5. Save to `~/Downloads/my.greenhouse.io.har`

### Step 2: Import Authentication

```bash
jj greenhouse setup --har ~/Downloads/my.greenhouse.io.har
```

This extracts:
- `x-csrf-token` - CSRF protection token
- `x-inertia-version` - Inertia.js version for SPA routing
- Session cookies

Credentials are saved to `~/.job-journal/greenhouse_auth.yaml`.

### Step 3: Configure Search Defaults

```bash
jj greenhouse config \
  --query "Product Manager" \
  --location "Austin, Texas, United States" \
  --lat 30.222346 \
  --lon -97.836521 \
  --date past_day
```

## Usage

### Poll for Jobs

```bash
# Use saved defaults
jj greenhouse poll

# Override with custom search
jj greenhouse poll --query "Senior PM" --date past_week

# Poll and import as prospects
jj greenhouse poll --import

# Poll with RAG scoring (requires `jj index` first)
jj greenhouse poll --score
```

### View Configuration

```bash
jj greenhouse config --show
```

## CLI Reference

### `jj greenhouse setup`

| Option | Description |
|--------|-------------|
| `--har, -h` | Path to HAR file (required) |

### `jj greenhouse poll`

| Option | Description |
|--------|-------------|
| `--query, -q` | Job title or keyword search |
| `--location, -l` | Location (e.g., "Austin, Texas") |
| `--date, -d` | Date filter: `past_day`, `past_week`, `past_month` |
| `--import, -i` | Import jobs as prospects |
| `--pages, -p` | Max pages to fetch (default: 3) |
| `--score, -s` | Score jobs against corpus |

### `jj greenhouse config`

| Option | Description |
|--------|-------------|
| `--show, -s` | Show current configuration |
| `--query, -q` | Set default search query |
| `--location, -l` | Set default location |
| `--lat` | Set latitude for location |
| `--lon` | Set longitude for location |
| `--date, -d` | Set default date filter |

## Data Files

| File | Purpose |
|------|---------|
| `~/.job-journal/greenhouse_auth.yaml` | Authentication credentials |
| `~/.job-journal/config.yaml` | Search defaults (under `greenhouse:` key) |
| `~/.job-journal/journal.db` | Applications table for imported prospects |

## API Details

The integration uses Greenhouse's internal Inertia.js API:

```
GET https://my.greenhouse.io/jobs
Headers:
  x-csrf-token: <from HAR>
  x-inertia: true
  x-inertia-version: <from HAR>
  x-inertia-partial-component: job_search
  x-inertia-partial-data: browsing,page,moreResultsAvailable,jobPosts,trackingData
  Cookie: <session cookies>

Query params: query, location, lat, lon, date_posted, page
```

Response contains `jobPosts` array with: `id`, `title`, `companyName`, `publicUrl`, `firstPublished`, `location`

## Session Expiration

Sessions typically expire after a few hours. If you see authentication errors:

1. Log into my.greenhouse.io in your browser
2. Export a fresh HAR file
3. Re-run `jj greenhouse setup --har <new-file>`

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "Authentication failed" | Re-export HAR and run setup again |
| "No jobs found" | Try broader search terms or remove date filter |
| Scoring shows "—" | Run `jj index` to index your corpus first |
| HAR parse error | Make sure to search on my.greenhouse.io before exporting |
