# /interview - Career Interview Session

Build your professional corpus through guided conversation.

## Usage

```
/interview              # Start or continue onboarding
/interview [role]       # Deep-dive on a specific role
/interview skills       # Audit and organize skills
/interview interests    # Mine personal interests for cover letter hooks
/interview stories      # Review and practice STAR+R story bank
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
| Has roles, all complete | None | Offer options (new role, deep-dive, skills, stories) |
| Any | `[role]` | Role Deep Dive on specified role |
| Any | `skills` | Skill Audit |
| Any | `interests` | Personal Connections |
| Any | `stories` | STAR+R Story Bank Review |

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

### Step 4.5: Personal Connections Interview (`/interview interests`)

Mine personal interests and hobbies for cover letter connection hooks. These create genuine, human openings that tie personal passions to professional contexts.

#### Phase 1: Seed from Profile (1 min)
```
[Read profile.yaml interests field]

"I see your interests include: [list from profile].
Let's turn these into stories you can use in cover letters.
We'll also explore what kinds of companies and missions excite you."
```

#### Phase 2: Story Mining (3-5 min per interest)

For each interest from the profile (and any new ones the user mentions):

```
"Let's talk about [interest].
- What got you into it? What keeps you doing it?"
[User responds]

"Has [interest] ever influenced how you think about product work or problem-solving?"
[User responds]

"If you were explaining to a hiring manager why [interest] makes you better at your job, what would you say?"
[User responds]
```

Also ask open-ended discovery questions:
```
"What kinds of companies or missions get you genuinely excited — not just as a job, but as problems you'd want to solve?"

"Any recent rabbit holes you've gone down outside of work? Podcasts, side projects, topics you can't stop reading about?"
```

#### Phase 3: Extract and Save (1 min per interest)

For each interest discussed, extract:
1. **Topic** — The interest name (e.g., "indie video games")
2. **Story** — 2-3 sentence anecdote capturing what they said
3. **Tags** — Industry/theme tags for matching to JDs:
   - Industry tags: `gaming`, `health`, `consumer`, `enterprise`, `creative`, `outdoor`
   - Abstract tags: `resilience`, `real-time`, `systems-thinking`, `collaboration`, `risk-management`
   - Technical tags: `ai`, `automation`, `data`, `infrastructure`, `design`
4. **Connection** — The professional bridge sentence (1-2 sentences linking the interest to work)

Confirm each before saving:
```
"Here's what I'd save for [topic]:

Story: [2-3 sentences]
Connection: [bridge sentence]
Tags: [tag list]

Sound right, or want to adjust anything?"
```

Save via:
```python
from jj.db import create_interest
create_interest(topic=topic, story=story, tags=tag_list, connection=connection)
```

#### Phase 4: Wrap Up
```
"We now have [N] interest hooks ready for cover letters.
When you use /apply, I'll automatically match these to job descriptions
and use them as genuine opening hooks in your cover letters.

To add more later: jj interests add <topic> --tags ... --connection ...
To review: jj interests list"
```

### Step 4.6: STAR+R Story Bank Review (`/interview stories`)

Review, refine, and practice your accumulated STAR+R stories. Stories are auto-generated during `/score` and `/pipeline` evaluations and stored in the `stories` table.

#### Phase 1: Load Story Bank

```python
from jj.db import get_stories

stories = get_stories()
```

If no stories exist:
```
"Your story bank is empty. Stories are automatically generated when you evaluate jobs with /score or /pipeline.

To build your story bank:
1. Run /score with a few job URLs — each evaluation generates 3-5 STAR+R stories
2. Or I can help you create stories manually from your corpus right now.

Want me to create stories from your existing corpus?"
```

If the user wants manual creation, read the corpus and guide them through crafting STAR+R stories from their strongest achievements (similar to the Role Deep Dive flow, but specifically structured as Situation → Task → Action → Result → Reflection).

#### Phase 2: Review Stories (sorted by least-used first)

Present stories sorted by `times_used` ASC (least-used first for variety):

```
## Your Story Bank (X stories)

### 1. "Scaled experimentation velocity at ZenBusiness" (used 0 times)
**Matches:** experimentation, A/B testing, growth
**S:** ZenBusiness needed to accelerate experiment throughput but the team was bottlenecked on setup and analysis...
**T:** Create a self-serve experimentation platform that any PM could use...
**A:** Built Terraform-based A/B testing infrastructure, integrated with analytics pipeline...
**R:** Scaled experimentation velocity 250%, reduced experiment setup from 2 weeks to 2 days...
**R (Reflection):** Learned that democratizing tools is more impactful than running experiments yourself...

### 2. "Built acquisition funnels driving 40% growth" (used 1 time)
...
```

#### Phase 3: Refine

For each story, offer refinement options:

```
"For each story, I can:
1. **Sharpen** — Tighten the wording for a specific interview context
2. **Expand** — Add more detail from your corpus
3. **Practice** — I'll ask you the behavioral question and you deliver the story
4. **Delete** — Remove if no longer relevant

Which story would you like to work on? (or 'next' to continue)"
```

**Sharpen:** Ask what role/company they're preparing for. Reframe the story emphasis to match that JD's requirements. Update `jd_requirements_matched` on the story.

**Expand:** Read related corpus entries (`source_entry_ids`) and suggest additional details or metrics to weave in.

**Practice:** Present a behavioral question that maps to the story's requirements (e.g., "Tell me about a time you had to scale a process"). Let the user deliver their answer, then give feedback on: structure (STAR completeness), specificity (metrics, names), length (aim for 2-3 minutes), and confidence signals.

After refinement:
```python
from jj.db import update_story

update_story(story_id, situation=refined_s, task=refined_t, ...)
```

#### Phase 4: Gap Analysis

After reviewing, identify gaps:

```
"Looking at your story bank coverage:

**Well covered:** experimentation, growth, AI/ML, team leadership
**Sparse:** stakeholder management (1 story), data infrastructure (0 stories)
**Missing:** conflict resolution, failure/recovery, cross-functional influence

Want me to help build stories for the gaps? I'll pull from your corpus."
```

#### Phase 5: Wrap Up

```
"Story bank review complete.
- X stories reviewed
- Y stories refined
- Z new stories created

Your stories are automatically matched to JD requirements during /score evaluations.
They're also surfaced when you use /apply to answer custom interview questions.

To practice specific stories: /interview stories
To add more: keep running /score — each evaluation adds new stories"
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
    create_interest,       # For /interview interests
    get_interests,         # For /interview interests
    get_stories,           # For /interview stories
    create_story,          # For /interview stories
    update_story,          # For /interview stories
    increment_story_usage, # For /interview stories
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
