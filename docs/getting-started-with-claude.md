# Getting Started with Claude Code

Job Journal is built to be driven by [Claude Code](https://claude.com/claude-code).
The fastest way to get from a fresh clone to a working, personalized setup is to
paste the prompt below into Claude Code **from the repo root**. Claude will install
the tool, initialize your data, build your corpus, and walk you through your first
real application — using *your* details, not the original author's.

## What you'll need

- **Python 3.10+** and **git**
- **[Claude Code](https://claude.com/claude-code)** running in the cloned repo
- *(Recommended)* A **Google Cloud project** with the Docs + Drive APIs enabled and
  an OAuth client (`credentials.json`) — this lets Job Journal export tailored
  resumes as formatted PDFs. You can skip it and still generate resume content.
- *(Optional)* Gmail API access if you want application emails auto-tracked.

Your personal data (profile, corpus, resumes, credentials) lives in `~/.job-journal/`
and `~/Documents/Resumes/` — **outside** the repo and gitignored — so cloning never
carries anyone else's information.

## The install prompt

Copy everything in the block below into Claude Code:

```text
You're setting up Job Journal for me — a job seeker — on my machine. Work through
these steps in order, pausing only when you need information or a decision from me.
Personalize everything to MY details; never reuse another person's data.

1. Confirm we're in the cloned job-journal repo root and Python 3.10+ is available.
2. Create and use a virtualenv, then install with dev/web/gmail extras:
     python3 -m venv .venv && source .venv/bin/activate
     pip install -e ".[dev,web,gmail]"
3. Initialize the data directory and database:  jj init
4. Run the /setup skill and walk me through creating my profile (full name, email,
   phone, location, LinkedIn, work authorization) and config. Save it to
   ~/.job-journal/profile.yaml.
5. Build my corpus — the verified source of truth that every resume bullet is
   selected from (never invented):
     - Run /interview to extract my work history role-by-role in my own words, OR
     - If I already have a resume / base.md, run `jj import-base <file>` then
       `jj corpus sync`, and we can refine with /interview afterward.
6. (Recommended) Set up resume PDF export: run `jj gdocs setup` and guide me through
   connecting a Google Cloud project (Docs + Drive APIs, OAuth credentials.json).
   If I skip this, note that resumes can still be generated but won't auto-export
   to formatted PDFs.
7. (Optional) If I want application emails auto-tracked, guide me through Gmail API
   auth. Otherwise skip.
8. (Optional) Help me set up a few resume "archetypes" — pre-built variants for the
   kinds of roles I target (e.g. general, growth, AI/platform) — in
   ~/.job-journal/archetypes.yaml, each assembled from my corpus.
9. Show me the day-to-day workflow and let me try it on ONE real job posting:
     - Discover + score roles against my corpus:  /jobs [query]   or  /greenhouse
     - Quick fit read on a specific posting:       /score <url>    or  /fit
     - Full tailored-resume application:           /apply <url>
       (or /apply-assist <url> to autofill an ATS form in my browser, stopping
        for my review before Submit)
     - See my pipeline:                            jj app status
     - Texas Workforce Commission compliance log:  /twc   (skip if I'm not in TX)
10. Tell me about the hands-off automation I can turn on later — /monitor (headless
    discovery + Slack alerts), /pipeline, /swarm, and /start-today for a morning
    routine — but don't enable any of it without my say-so.

Before finishing, scan for anything that still hard-codes the previous owner's
identity (e.g. the author email in pyproject.toml, a template filename in
jj/resume_gen.py) and offer to update it to mine. Use the programmatic resume
generator, not the legacy template path.
```

## After setup

Your daily loop is **discover → score → apply → track**:

| Step | Skill / command |
|------|------------------|
| Discover & score jobs | `/jobs`, `/greenhouse` |
| Score a specific posting | `/score <url>`, `/fit` |
| Apply with a tailored resume | `/apply <url>`, `/apply-assist <url>` |
| Draft a cover letter | `/cover-letter` |
| Track status & email | `jj app status`, `/twc` |
| Automate it | `/monitor`, `/pipeline`, `/swarm`, `/start-today` |

See the [README](../README.md) for the full CLI reference, and run `/setup` any time
to diagnose what's missing.
