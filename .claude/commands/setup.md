# /setup - Guided Onboarding

Walk new users through Job Journal setup, or diagnose what's missing for existing users.

## Usage

```
/setup          # Check state and guide through any missing setup
```

## Workflow

When the user invokes `/setup`, run through each check silently. Only prompt for items that are missing or incomplete.

### Step 1: Data Directory

Check if `~/.job-journal/` exists:

```python
from jj.config import JJ_HOME, DB_PATH

if not JJ_HOME.exists():
    # Initialize everything
    from jj.db import init_database
    init_database()
    print("Created ~/.job-journal/ and initialized database.")
```

If it exists, verify the database is accessible:

```python
if not DB_PATH.exists():
    from jj.db import init_database
    init_database()
```

### Step 2: Profile

Check `~/.job-journal/profile.yaml`:

```python
from jj.config import load_profile

profile = load_profile()
```

**If missing or empty**, ask the user:

```
I need a few details to personalize Job Journal:

1. Full name
2. Email address
3. Phone number
4. Location (city, state)
5. LinkedIn URL
6. Work authorization (e.g., "US Citizen", "H-1B", "Green Card")
```

Save via:
```python
from jj.config import save_profile

save_profile({
    "name": name,
    "email": email,
    "phone": phone,
    "location": location,
    "linkedin": linkedin,
    "work_auth": work_auth,
})
```

**If exists**, show what's configured and ask if anything needs updating.

### Step 3: Config

Check `~/.job-journal/config.yaml`:

```python
from jj.config import load_config, save_config

config = load_config()
```

**If missing**, save defaults:
```python
save_config()  # Creates with DEFAULT_CONFIG
```

**If exists**, verify key fields are set:
- `resume_template_id` (Google Docs template ID)
- `variants` (resume variant definitions)

If `resume_template_id` is empty, note it for Step 5.

### Step 4: Corpus

Check `~/.job-journal/corpus.md`:

```python
from jj.config import CORPUS_PATH

if not CORPUS_PATH.exists() or CORPUS_PATH.stat().st_size < 100:
    # No corpus yet
```

**If missing or nearly empty**, offer two paths:

```
Your professional corpus is empty. This is what powers resume generation and job scoring. Two options:

1. **Paste your resume** — I'll import it as a starting corpus (fastest)
2. **Start /interview** — I'll guide you through a conversational deep-dive on each role (best quality)

Which do you prefer?
```

If they paste a resume, parse it into roles and entries using `create_role()` and `create_entry()`, then regenerate `corpus.md`.

If they choose interview, tell them to run `/interview` after setup completes.

### Step 5: Google Docs Template

Check if the resume template is configured:

```python
config = load_config()
template_id = config.get("resume_template_id", "")
```

**If empty**, explain:

```
Resume generation uses a Google Docs template. To set this up:

1. Create or copy a resume template in Google Docs
2. Note the document ID from the URL: docs.google.com/document/d/{THIS_PART}/edit
3. Run: jj config set resume_template_id <your-template-id>

You can skip this for now and set it up later when you're ready to generate resumes.
```

Also check for Google Docs credentials:

```python
creds_path = JJ_HOME / "credentials.json"
if not creds_path.exists():
    # Note: credentials.json must come from Google Cloud Console
```

If missing, explain:
```
Google Docs integration requires OAuth credentials from Google Cloud Console.
See the README for setup instructions. This is optional — you can use Job Journal
for scoring and tracking without resume generation.
```

### Step 6: Gmail Integration

Check Gmail token:

```python
token_path = JJ_HOME / "gmail_token.json"
creds_path = JJ_HOME / "credentials.json"
```

**If credentials exist but no token:**
```
Gmail integration is available but not authenticated yet.
Run this from your terminal (not from Claude Code — it needs a browser):

    jj email setup

This enables email sync for automatic application status tracking.
```

**If no credentials:**
```
Gmail integration is optional. It enables automatic status tracking
by monitoring your inbox for application confirmations and responses.
To set it up later, add credentials.json and run: jj email setup
```

### Step 7: Summary

Present a status dashboard:

```
## Setup Status

| Component | Status | Notes |
|-----------|--------|-------|
| Data directory | Ready | ~/.job-journal/ |
| Database | Ready | 16 tables initialized |
| Profile | Ready | Don Hogan, Austin, TX |
| Config | Ready | 5 variants configured |
| Corpus | [X entries] | Run /interview to add more |
| Google Docs | [Ready/Not configured] | [template ID or "needs setup"] |
| Gmail | [Ready/Not configured] | [status] |

## Next Steps
- `/interview` — Build your professional corpus (recommended first step)
- `/score <url>` — Score a job posting against your corpus
- `/pipeline` — Run the full autonomous job search pipeline
- `/start-today` — Morning startup routine
```

## Notes

- This skill is idempotent — running it again just re-checks everything
- Never overwrite existing data — only fill in what's missing
- Profile and config are created with sensible defaults; the user can always edit later
- Google Docs and Gmail are optional — Job Journal works for scoring and tracking without them
- If everything is already configured, just show the summary dashboard and suggest next steps
