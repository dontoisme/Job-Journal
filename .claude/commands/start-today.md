# /start-today - Morning Startup Routine

Daily morning briefing that syncs email, reviews the pipeline, checks TWC compliance, and surfaces what needs attention today. Run this first thing each morning.

---

## Step 1: Email Sync

Sync application emails to catch overnight responses (rejections, interviews, next steps).

```bash
python3 -c "
from pathlib import Path
token = Path.home() / '.job-journal' / 'gmail_token.json'
print(f'TOKEN_EXISTS={token.exists()}')
"
```

If token exists, run sync:
```bash
jj email sync --days 3 --verbose
```

If token missing, print: "Gmail token not found. Run `jj email setup` from your terminal."

Summarize what changed: new confirmations, resolutions, status transitions.

---

## Step 2: Overnight Monitor Results

Check what the monitor found since yesterday.

```bash
python3 -c "
import json
from pathlib import Path
f = Path.home() / '.job-journal' / 'logs' / 'monitor-latest.json'
if f.exists():
    data = json.loads(f.read_text())
    jobs = data.get('new_jobs', [])
    summary = data.get('summary', {})
    email_sync = data.get('email_sync', {})
    print(json.dumps({'jobs': len(jobs), 'summary': summary, 'email_sync': email_sync}))
else:
    print('{\"jobs\": 0, \"error\": \"no monitor data\"}')
"
```

Summarize: how many new listings, top prospects by score, any email sync results from the monitor run.

---

## Step 3: Active Prospects Review

Show prospects that need attention today.

```bash
python3 -c "
import json
from jj.db import get_applications
prospects = get_applications(status='prospect')
# Sort by fit_score descending
prospects.sort(key=lambda x: x.get('fit_score') or 0, reverse=True)
# Show top 10
for p in prospects[:10]:
    print(f\"{p['id']:>4} | {p.get('fit_score', '?'):>3} | {p['company']} — {p.get('position', '?')} | {p.get('location', '?')}\")
print(f'--- {len(prospects)} total prospects ---')
"
```

Present as a ranked list. For the top 3-5, ask: "Want to review any of these? I can score the full JD or start an application."

---

## Step 4: Pipeline Status

Show active applications and what's pending.

```bash
python3 -c "
import json
from jj.db import get_applications
from collections import Counter

apps = get_applications()
statuses = Counter(a['status'] for a in apps)
print(json.dumps(dict(statuses)))

# Applications waiting for response (applied > 7 days ago, no update)
from datetime import datetime, timedelta
cutoff = (datetime.now() - timedelta(days=7)).isoformat()
stale_apps = [a for a in apps if a['status'] == 'applied' and (a.get('applied_at') or '') < cutoff and not a.get('latest_update_at')]
print(f'STALE_APPS={len(stale_apps)}')

# Recent activity (last 3 days)
recent_cutoff = (datetime.now() - timedelta(days=3)).isoformat()
recent = [a for a in apps if (a.get('updated_at') or '') >= recent_cutoff]
print(f'RECENT_UPDATES={len(recent)}')
"
```

Present a quick status summary:
- Pipeline: X applied, Y screening, Z interview
- Stale: N applications with no response in 7+ days
- Recent: N updates in last 3 days

---

## Step 5: TWC Compliance Check

Check if this week's TWC work search requirements are met.

```bash
python3 -c "
import json
from datetime import date
from jj.db import get_twc_week_summary, get_twc_week_boundaries

# Current week (Sunday-Saturday)
today = date.today()
# Find this week's Sunday
days_since_sunday = today.weekday() + 1 if today.weekday() != 6 else 0
sunday = today.replace(day=today.day - days_since_sunday) if days_since_sunday <= today.day else today
week_start, week_end = get_twc_week_boundaries(sunday.isoformat())
summary = get_twc_week_summary(week_start)
print(json.dumps({
    'week': f'{week_start} to {week_end}',
    'activities': summary.get('activity_count', 0),
    'required': 3,
    'compliant': summary.get('activity_count', 0) >= 3,
}))
"
```

If compliant: "TWC: 3/3 activities this week. You're good."
If not: "TWC: X/3 activities this week. Need Y more by Saturday."

---

## Step 6: Today's Action Items

Based on everything above, generate a prioritized list of 3-5 things to do today:

1. **Urgent:** Any interview prep needed? Expiring deadlines?
2. **High:** Top prospect to apply to (highest corpus-fit score)
3. **Medium:** Follow up on stale applications (7+ days no response)
4. **TWC:** If not compliant, suggest specific activities to hit 3/3
5. **Triage:** Archive stale prospects, review new monitor finds

Present as a numbered checklist. Keep it actionable — link to specific commands:
- "Apply to X: run `/apply <url>`"
- "Score prospect Y: run `/score <url>`"
- "Archive stale prospects: visit http://localhost:8000/prospects"

---

## Output Format

Present everything in a single concise briefing. Use headers for each section but keep it tight. End with the action items. This should take < 60 seconds to read.
