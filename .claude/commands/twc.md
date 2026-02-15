# /twc - TWC Compliance Sync & Dashboard

Sync recent emails and open the TWC compliance dashboard. Ensures your work search activity log is current before review.

## Workflow

When the user invokes `/twc`, execute these three steps in order:

### Step 1: Email Sync

Run email sync to capture confirmations and updates across the full claim period:

```bash
jj email sync --days 14
```

If this fails (Gmail not configured, auth expired, etc.), warn the user but **continue** — the dashboard still works from existing DB data:

```
Warning: Email sync failed — proceeding with existing data.
If you need fresh data, run `jj email setup` to configure Gmail.
```

### Step 2: Compliance Summary

Query the database and display a quick summary in the terminal:

```python
from jj.db import get_twc_week_summary, get_all_twc_claim_periods

# Current week
summary = get_twc_week_summary()
total = summary['total_activities']
required = summary['required_activities']
status = "COMPLETE" if summary['is_complete'] else f"NEEDS {required - total} MORE"

# Find the latest UNSUBMITTED claim period (the one due for payment request)
periods = get_all_twc_claim_periods()
actionable = None
for p in periods:
    w1_submitted = p['week1'].get('payment', {}).get('submitted', False)
    w2_submitted = p['week2'].get('payment', {}).get('submitted', False)
    if not w1_submitted or not w2_submitted:
        # Skip the current/future period (no activities yet and starts today or later)
        if p['week1']['activity_count'] == 0 and p['week2']['activity_count'] == 0:
            continue
        actionable = p
        break
```

Display like this:

```
## TWC Compliance Status

**Current week** (Sun {week_start} — Sat {week_end}): {total}/{required} activities — {status}

Activity breakdown: {activities_by_type summary}

**Payment request due** ({actionable period_display}):
  Claim Week 1 ({week1 display}): {activity_count}/3 activities — {COMPLETE/NEEDS N MORE}
  Claim Week 2 ({week2 display}): {activity_count}/3 activities — {COMPLETE/NEEDS N MORE}
  Period status: {READY TO SUBMIT / INCOMPLETE}
```

The key dict fields are:
- `p['period_display']` — e.g., "Feb 01 - Feb 14, 2026"
- `p['week1']['display']`, `p['week1']['activity_count']`, `p['week1']['is_complete']`
- `p['week2']['display']`, `p['week2']['activity_count']`, `p['week2']['is_complete']`

### Step 3: Open Dashboard

Launch the web dashboard directly to the TWC page:

```bash
jj serve --path /twc
```

This opens the browser to `http://127.0.0.1:8000/twc` where the user can review detailed activity logs, edit TWC fields, and prepare payment requests.

## Notes

- The 14-day sync window covers a full TWC biweekly claim period
- TWC requires 3+ work search activities per week (Sunday–Saturday)
- Every 2 weeks, a payment request is submitted proving compliance
- The dashboard at `/twc` shows the full interactive view with editing capabilities
