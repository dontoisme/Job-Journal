# Getting Started with Job Journal

A guide to setting up your job search system from scratch.

---

## Prerequisites

1. Python 3.11+
2. Google Cloud credentials (for Google Docs API)
3. Claude Code CLI

---

## Step 1: Initialize Configuration

Your config lives in `~/.job-journal/`:

```bash
# Created automatically on first run, but you can set up manually:
mkdir -p ~/.job-journal
```

### profile.yaml (Your Identity)

```yaml
name:
  first: Your
  last: Name
  preferred: Your

contact:
  email: you@example.com
  phone: "555-123-4567"
  location: Austin, TX

links:
  linkedin: https://linkedin.com/in/yourprofile

work_authorization: US Citizen
years_experience: 10
current_company: Your Company
current_title: Your Title

# Resume summaries by variant
summaries:
  general: |
    Your default 3-4 sentence professional summary.

  growth: |
    Growth-focused variant summary.

  # Add more variants as needed
```

### config.yaml (System Settings)

```yaml
output:
  gdrive_folder: ~/Google Drive/My Drive/Job Applications/
  naming_pattern: Your Name - {title} - {company} - Resume
  default_format: docx

google_docs:
  template_id: YOUR_TEMPLATE_DOC_ID
```

---

## Step 2: Build Your Corpus

Your resume corpus is the foundation. Use `/interview` to add experiences.

### Add Your Work History (Roles)

```
/interview

> Let's add your work history. What company did you work at?
Acme Corp

> What was your title?
Senior Product Manager

> When did you start? (YYYY-MM)
2020-01

> When did you leave? (or "present")
2023-06
```

### Add Experience Bullets (Entries)

For each role, add accomplishment bullets:

```
/interview

> Let's add accomplishments for your role at Acme Corp.
> Tell me about a key achievement.

Led the redesign of the checkout flow, increasing conversion by 23%
and reducing cart abandonment from 68% to 52%.

> What tags apply? (growth, technical, leadership, etc.)
growth, conversion, e-commerce
```

**Tips for great bullets:**
- Start with action verbs (Led, Built, Drove, Launched)
- Include metrics where possible (%, $, time saved)
- Be specific about scope and impact
- Keep under 2 lines

### Add Skills

Skills are added by category:

```sql
-- Via direct DB or through interview
INSERT INTO skills (name, category) VALUES
  ('Product Strategy', 'product-management'),
  ('SQL', 'analytics-&-tools'),
  ('API Design', 'technical');
```

---

## Step 3: Add Target Companies

Build your hit list:

```bash
# Via CLI
jj company add "Stripe" --industry fintech --priority 1

# Or via web UI
# http://localhost:8787/companies
```

**Key fields:**
- `name` — Company name
- `industry` — For filtering
- `target_priority` — 1 (top) to 5 (opportunistic)
- `careers_url` — For job discovery
- `ats_type` — greenhouse, lever, etc. (for future auto-polling)
- `notes` — Why you're interested

---

## Step 4: Set Up Google Docs Template

1. Create a Google Doc with placeholders:
   - `{{name}}` — Your full name
   - `{{email}}`, `{{phone}}`, `{{location}}`, `{{linkedin}}`
   - `{{summary}}` — Professional summary
   - `{{skill_category1}}` through `{{skill_category5}}`
   - `{{skill_list1}}` through `{{skill_list5}}`

2. Get the document ID from the URL:
   ```
   https://docs.google.com/document/d/THIS_IS_THE_ID/edit
   ```

3. Add to config.yaml:
   ```yaml
   google_docs:
     template_id: THIS_IS_THE_ID
   ```

---

## Step 5: Generate Your First Resume

```
/resume-workflow Stripe "Senior Product Manager"

> Paste the job description so I can optimize:
[paste JD]

> What's your pitch for this role?
I have 5 years building payment products and love the complexity
of B2B fintech. At Acme I owned our payments integration...

[Generates resume, scores against JD, delivers PDF]
```

---

## Corpus Health Checklist

Before your first application, ensure:

| Item | Minimum | Ideal |
|------|---------|-------|
| Roles | All recent jobs | Last 10-15 years |
| Entries per role | 3-4 bullets | 6-8 bullets |
| Skills | 15+ | 25+ across categories |
| Tags | Basic set | Rich taxonomy |
| Companies | 10 targets | 50+ |

---

## Quick Reference

| Task | Command |
|------|---------|
| Add experience | `/interview` |
| Find jobs | `/greenhouse` or `/hunt` |
| Browse prospects | `/jobs` |
| Generate resume | `/resume-workflow [company] [position]` |
| Apply to job | `/apply` |
| Check status | `/track` |

---

## Next Steps

1. **Build corpus depth** — Add 5+ bullets per role
2. **Tag everything** — Makes bullet selection easier
3. **Add 20+ target companies** — Your hunting ground
4. **Create variant summaries** — growth, technical, leadership angles
5. **Start applying** — See [Daily Workflow](daily-workflow.md)
