# Daily Job Hunt Workflow

A typical session using Job Journal.

---

## Morning Routine (15-30 min)

### 1. Check for New Jobs

```
/greenhouse
```

Or search your target companies:

```
/hunt
```

Review what's new. For interesting roles, add as prospects.

### 2. Check Email for Updates

```bash
python -m jj.cli email updates
```

This scans Gmail for application-related emails and categorizes them:
- **REJECTION** — Application closed
- **ACTION** — Form to complete, interview to schedule
- **UPDATE** — Status change, check the email

For each update, decide:
- Update application status in database
- Follow up if action required
- Archive if just a confirmation

Other email commands:
```bash
python -m jj.cli email sync      # Full sync (verify + updates)
python -m jj.cli email verify    # Check for missing confirmations
python -m jj.cli email report    # Show email pairing status
```

### 3. Review Active Applications

```
/track
```

Check statuses:
- Any responses to follow up on?
- Any interviews to prep for?
- Any rejections to process?

### 4. Update Application Statuses

When you get emails:
- "We'd like to schedule a call" → `recruiter_screen`
- "The hiring manager would like to meet" → `hiring_manager`
- "We're moving forward with other candidates" → `rejected`

---

## Application Session (30-60 min per app)

### Step 1: Pick a Prospect

Choose from your reviewed prospects or find a new role:

```
/jobs
```

Look for:
- High fit score (70+)
- Companies you're excited about
- Roles that match your experience

### Step 2: Read the JD Carefully

Before generating, understand:
- **Must-haves** — What they absolutely need
- **Nice-to-haves** — Bonus points
- **Red flags** — Anything concerning
- **Keywords** — Terms to echo in your resume

### Step 3: Generate Tailored Resume

```
/resume-workflow [company] [position]
```

When prompted:
1. **Paste the full JD** — Needed for scoring
2. **Craft your pitch** — Why you're a great fit (2-3 sentences)

The workflow will:
- Generate resume with custom summary
- Score against JD
- Optimize skill ordering
- Deliver PDF

**Target score: 80+** before submitting.

### Step 4: Review Output

Check the generated resume:
- [ ] Summary reads as a compelling pitch for THIS role
- [ ] Skills are ordered by JD relevance
- [ ] Top bullets support your narrative
- [ ] No weird formatting issues

### Step 5: Apply

Submit via the company's ATS. Track it:

```
/apply
```

Or update manually:
```python
# Convert prospect to application
from jj.db import create_application_from_prospect
create_application_from_prospect(prospect_id, resume_id)
```

---

## Weekly Review (30 min)

### Pipeline Health Check

| Stage | Healthy | Action if Low |
|-------|---------|---------------|
| Prospects | 10+ | Hunt more roles |
| Applied (this week) | 5-10 | Increase velocity |
| In Progress | 3-5 | Good signal |
| Interviews | 1-2 | Pipeline working |

### Corpus Maintenance

- Add new accomplishments from recent work
- Refine bullet phrasing based on what's resonating
- Add new skills you've been using

### Company List Updates

- Add companies that caught your eye
- Update notes on companies you've researched
- Set fit scores based on what you've learned

---

## Quick Actions

| I want to... | Command |
|--------------|---------|
| Check for email updates | `python -m jj.cli email updates` |
| Find new jobs | `/greenhouse` or `/hunt` |
| See my prospects | `/jobs` |
| Make a resume | `/resume-workflow [company] [role]` |
| Score a resume | `/score` |
| Track an application | `/track` |
| Add experience | `/interview` |

---

## Efficiency Tips

### Batch Similar Roles

If applying to multiple PM roles:
1. Generate base resume for "Product Manager" archetype
2. Customize summary for each company
3. Adjust skills order per JD

### Reuse Good Summaries

When a custom summary works well, save the pattern:
```
[Hook with years + specialty]
[Proof point with metrics]
[Value prop for this type of role]
```

### Track What Converts

Note which bullets and summaries lead to interviews. Use `times_used` on entries to see what you're leaning on.

---

## Sample Session Log

```
9:00 AM - /greenhouse → Found 3 new PM roles
9:15 AM - Added 2 as prospects, 1 didn't match
9:30 AM - /resume-workflow Figma "Senior PM"
         - Pasted JD, crafted summary
         - Score: 82/100 ✓
         - Submitted via Greenhouse
10:00 AM - /track → Updated Stripe to "recruiter_screen"
10:15 AM - Prepped for Stripe screen tomorrow
10:30 AM - Done for today
```

---

## When Things Go Wrong

### Low Scores (<70)

- Summary doesn't match JD keywords
- Wrong skill categories prioritized
- Solution: Rewrite summary, reorder skills

### No Callbacks

- Bullets may not demonstrate impact
- Summary may be too generic
- Solution: A/B test different positioning

### Application Fatigue

- Batch similar applications
- Use variants for common role types
- Take breaks - quality > quantity
