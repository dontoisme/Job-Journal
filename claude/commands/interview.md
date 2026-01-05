# /interview - Career Interview Session

Build your professional corpus through guided conversation.

## Usage

```
/interview              # Start or continue onboarding
/interview [role]       # Deep-dive on a specific role
/interview skills       # Audit and organize skills
```

## Workflow

When the user invokes `/interview`, follow this process:

### Step 1: Check Status

1. Check if Job Journal is initialized (`~/.job-journal/` exists)
2. If not, prompt user to run `jj init` first
3. Load current corpus stats from database

### Step 2: Determine Mode

Based on corpus state and arguments:

| State | Argument | Mode |
|-------|----------|------|
| No roles | None | Onboarding |
| Has roles, some incomplete | None | Continue incomplete role |
| Has roles, all complete | None | Offer options (new role, deep-dive, skills) |
| Any | `[role]` | Role Deep Dive on specified role |
| Any | `skills` | Skill Audit |

### Step 3: Onboarding Flow (First Time)

For users with no roles yet:

#### Phase 1: Profile Verification (2 min)
```
"Let me check your profile first..."
[Read ~/.job-journal/profile.yaml]

"I see you're [Name] based in [Location]. Is that correct?"
- If needs updates, collect them
- Verify: email, phone, LinkedIn, work authorization
```

#### Phase 2: Career Timeline (10 min)
```
"Let's map out your career. Starting with your current role and working backwards:

What's your current title and company?"

For each role:
- Title
- Company
- Approximate dates (month/year)
- Location

"Are there any other roles I should know about?"

After collecting all:
"Great, I have [N] roles spanning [X] years. Which roles are most relevant to your current job search?"
```

Save roles to database with `interview_complete = false`.

#### Phase 3: First Role Deep Dive (15-20 min)
```
"Let's start with your most recent role: [Title] at [Company].

Tell me about this role - what was the company doing, and what were you brought in to accomplish?"
```

Then proceed to Role Deep Dive flow (Step 4).

### Step 4: Role Deep Dive Flow

For each role, extract 8-15 bullets through conversation:

#### Phase 1: Context (2-3 min)
```
"Tell me about your time at [Company]:
- What was the company's mission?
- What team were you on?
- What was the state of things when you joined?"
```

Save context as role summary.

#### Phase 2: Achievement Mining (10-15 min)

Ask questions one at a time, probing for details:

**Shipping:**
```
"What's something you shipped that you're proud of?"
[User responds]
"What was the impact? Do you have any metrics?"
[User responds]
"Let me draft that as a bullet:
  '- Shipped [X], resulting in [Y]'
Does that sound like you, or should I phrase it differently?"
```

**Metrics/Numbers:**
```
"Did you move any metrics in this role? Growth numbers, efficiency gains, cost savings?"
```

**Problem Solving:**
```
"What was broken when you arrived that you helped fix?"
```

**Building:**
```
"Did you build anything from scratch? New products, teams, processes?"
```

**Influence:**
```
"Tell me about a time you had to influence without direct authority."
```

**Technical:**
```
"What technical challenges did you navigate? APIs, architecture decisions, tool choices?"
```

For each answer:
1. Probe for specifics and metrics
2. Draft a bullet
3. Confirm the wording sounds like them
4. Note if they resist certain phrasings (add to `voice.avoids`)
5. Save to database with appropriate tags

#### Phase 3: Skills (3 min)
```
"What tools and technologies did you use daily in this role?"
"What skills did you develop or demonstrate?"
```

Save skills with links to entries as evidence.

#### Phase 4: Wrap Up (2 min)
```
"Let me summarize this role in 2 sentences for your resume:
  '[Summary draft]'
How does that sound?"
```

Mark role as `interview_complete = true`.

Show progress:
```
"Great work! We captured [N] bullets from [Role].
Your corpus now has [Total] entries across [M] roles.

[If more incomplete roles exist:]
Want to continue with [Next Role], or take a break?"
```

### Step 5: Voice Capture (Throughout)

During the interview, note:

**Phrases they like:**
- When they say something memorable, note it: "I love how you phrased that - 'shipped not just built'. I'll remember that style."

**Phrases they dislike:**
- If they push back: "Hmm, 'leveraged' feels corporate to me."
- Save to `profile.yaml` under `voice.avoids`

**Tone observations:**
- Direct vs. narrative
- Technical depth preference
- First person vs. third person

### Step 6: Save and Generate

After each interview session:
1. Save all entries to database
2. Regenerate `corpus.md` from database
3. Show updated stats

```
"Session complete! Your corpus has been updated.

You can review/edit at: ~/.job-journal/corpus.md
Or run 'jj corpus --edit' to open in your editor.

To continue building, run '/interview [next-role]'
To apply for a job, run '/apply <job-url>'"
```

---

## Database Operations

Use these Python functions to interact with the database:

```python
from jj.db import (
    create_role,
    create_entry,
    get_roles,
    get_entries_for_role,
    get_stats,
)
from jj.parser import generate_corpus_md
from jj.config import load_profile, save_profile
```

## Interview Prompts Cheat Sheet

**Opening a role:**
> "Tell me about your time at [Company]. What was the situation when you joined, and what were you brought in to do?"

**Mining achievements:**
> "What's the thing you're most proud of shipping?"
> "What metrics did you move? By how much?"
> "What was broken that you fixed?"
> "What did you build from scratch?"

**Probing for detail:**
> "Can you tell me more about the impact?"
> "Do you remember the numbers?"
> "What made this challenging?"

**Confirming voice:**
> "Here's how I'd phrase that: '[bullet]'. Sound like you?"
> "Is there a different way you'd say that?"

**Closing:**
> "Great session! We captured [N] bullets from [Role]. Your corpus now has [Total] entries."

---

## Notes

- Always pause after drafting bullets to confirm voice
- Don't rush - quality over quantity
- If user seems tired, offer to pause and continue later
- Each role should yield 8-15 bullets
- Tag every entry with relevant themes
- Extract metrics whenever mentioned
