# Job-Journal Pipeline Refinement Notes

**Source:** Lattice Staff PM, AI application (gh_jid 8523623002), reviewed against JD pulled from Lattice careers and historical archived versions of the same role family.

**Pipeline run summary:** 4-phase pipeline (slack-apply → opus eval → refine → opus eval) returned Fit: 84 (Strong Fit) on the refined output. The refinement scored higher than its input but produced a document that reads worse to a human reviewer than either the freeform or strict variant. The refined version should not have won.

---

## Core finding: the pipeline is measuring the wrong thing

The refinement and final-eval phases reward JD-language density. They do not penalize over-tailoring tells. As a result, the refinement pass injects more JD vocabulary, the eval pass scores it higher, and the system ships the version most likely to read as AI-tailored to a real human reviewer.

Two failure modes are now visible across multiple applications (OpenAI run, Lattice run):

1. The pipeline produces a "refined" version that scores highest but contains content that breaks credibility (named-company-areas inserted into past-tense bullets, grammar collapse from vocabulary injection, displacive JD paraphrasing).
2. The pipeline produces a "freeform" version that is closer to what a disciplined human PM would actually submit, but scores lower because it has less JD-keyword density.

The system is optimizing for keyword match against JD text. It should be optimizing for "would this resume earn a screen from a human reviewer who has seen 200 AI-tailored resumes this month."

---

## Specific defects in the Lattice refined output

### Defect 1: Past-tense bullet editorializing about the target company's current org

The refined Mattermost bullet 2 reads:

> "Established a Growth Tiger Team spanning Product, Engineering, Marketing, and Sales to align growth loops across functions, the cross-functional pattern Lattice's Reviews, Grow, and Calibration teams require to ship one coherent AI surface"

This bullet describes work performed at Mattermost in 2021-2023 and then editorializes about what Lattice's product teams "require" in 2026. No real candidate writes this naturally. It is transparently model-generated alignment text. A hiring manager who has reviewed AI-tailored resumes can identify this pattern in seconds.

This is the single highest-cost defect because it converts an otherwise strong document into a credibility liability.

### Defect 2: Grammar collapse from JD vocabulary injection

The refined Wellcore bullet 1 reads:

> "Built workflow orchestration system coordinating tasks across patients, providers, labs, and pharmacies, with multi-stakeholder structured workflow with data capture, AI synthesis, and human-in-the-loop action that automated multi-step processes previously requiring manual coordination"

The bullet contains two stacked "with" clauses, redundant phrasing ("multi-stakeholder structured workflow"), and unclear sentence structure. The freeform version of the same bullet is clean. The refinement pass tried to inject Lattice's "data capture / AI synthesis / human-in-the-loop" vocabulary into a working bullet and broke its syntax in the process.

This is a symptom of the deeper issue: the refinement pass is doing string-level vocabulary substitution rather than meaning-preserving rewriting.

### Defect 3: Mode-distinguishing language showing up unevenly

The refined version shows symptoms of being generated under different framing than the freeform/strict versions. Skills section reorganized into "AI & Trustworthy Systems" (vs. "AI & Machine Learning"). Indeed cut to 2 bullets (vs. 3 in freeform). One Mattermost bullet rewritten to insert Lattice product names. These changes individually are minor but collectively suggest the refinement phase is treating the input as raw material to be transformed rather than as a near-final document to be lightly improved.

---

## Recommended pipeline changes

### 1. Add an over-tailoring penalty to the eval phase

The phase 2 and phase 4 eval prompts should explicitly deduct from fit scores for the following patterns. This is additive to existing scoring criteria, not replacement.

**Hard deductions (score floor 60 if any present):**

- Bullets that name the target company's product areas, teams, or org structure (e.g. "Lattice's Reviews, Grow, and Calibration teams")
- Bullets describing past roles using forward-looking JD framing (e.g. "the pattern X needs to ship Y")
- Verbatim JD phrases of 5+ consecutive words appearing in resume bullets
- Grammar errors visible on first pass (stacked prepositions, redundant modifiers, unclear referents)

**Soft deductions (5-10 point reduction):**

- Sentences that paraphrase the JD's own phrasing back at the reviewer with light rewording
- Skill category names that mirror unusual JD phrasing rather than industry-standard taxonomy (e.g. "Trustworthy Systems" when "AI & Machine Learning" is the conventional label)
- Bullet density in the summary above ~3 distinct JD keyword phrases

The goal is to make the eval phase capable of recognizing that high keyword density past a certain threshold is a negative signal, not a positive one.

### 2. Constrain the refinement phase

The refinement pass currently has too much latitude. It should be allowed to:

- Reorder bullets within roles
- Swap one bullet for another from the corpus (same role only)
- Adjust skill category ordering
- Compose a fresh summary using the Identity-First framework

It should not be allowed to:

- Generate new bullet text
- Inject company-specific product names, team names, or org structure into past-tense bullets
- Substitute words inside corpus bullets to match JD vocabulary
- Restructure the document layout (Indeed bullet count, etc.)

In practice this means the refinement phase should operate under disciplined-mode constraints (the SWAP/CUT/PROMOTE/DEMOTE whitelist already specified for /apply), not freeform-mode constraints. Currently it appears to be operating under freeform constraints with no integrity audit at the end.

### 3. Run the existing integrity audit on refinement output

The Python-layer `_pre_export_audit()` function specified in the disciplined-mode design should run on refinement output before it's accepted as the pipeline's final answer. The defects above (Defect 1 and Defect 2) would have been caught by an audit check that flags:

- Bullets containing the target company's name (suspicious unless explicitly intended)
- Bullets exceeding a length threshold without compensating density (suggests stacked clauses)

These checks don't exist yet but should be added as part of v1.2.

### 4. Treat freeform as a tied output, not a fallback

When the pipeline produces freeform, strict, and refined variants, the current logic appears to select the highest-scoring variant. This should change to: the pipeline presents all three to the user (or to Slack) and explicitly notes when the refined version's score advantage is small (less than 5 points) and the refined version contains any over-tailoring tells.

When in doubt, freeform should win the tiebreaker. Disciplined corpus bullets in clean prose beat keyword-stuffed corpus bullets every time.

---

## The deeper pattern worth noting

Across two pipeline runs (OpenAI and Lattice), the same dynamic has emerged: the refinement phase produces a document that scores well against an LLM eval and reads poorly to a human eye. This is not a bug in any individual phase. It's a calibration mismatch between the eval rubric and the actual selection criteria of human recruiters at high-prestige targets.

Recruiters at OpenAI, Lattice, Anthropic, and similar companies in 2026 are reading hundreds of AI-tailored resumes per req. Their pattern recognition for AI-generated content is significantly better than it was 12 months ago. Resumes that mirror JD language tightly are now correlated with low-effort applications, not high-effort ones.

The pipeline should treat JD-language mirroring above a threshold as a tell, not as evidence of fit.

---

## Implementation priority

1. **High:** Add over-tailoring deductions to phase 2 and phase 4 eval prompts (concern 1 above). Largest single improvement, lowest implementation cost.
2. **High:** Constrain refinement phase to disciplined-mode operations (concern 2). Closes the dominant failure mode.
3. **Medium:** Extend `_pre_export_audit()` to flag company-name injection and grammar collapse (concern 3). Catches what gets through the prompt-level constraints.
4. **Low:** Adjust tiebreaker logic to favor freeform when refined-vs-freeform delta is small (concern 4). Polish.

---

## Test cases to validate the fix

After implementing changes, re-run the pipeline against the Lattice JD and confirm:

- The refined output does not contain "Lattice" anywhere except possibly in a single skills-context reference
- No bullet exceeds 35 words
- No bullet contains 5+ consecutive verbatim words from the JD
- The eval score for the freeform variant is within 3 points of the refined variant (currently the refined variant probably scored 5-10 points higher than freeform; that gap should close)

If after these changes the refined variant still consistently wins by more than 3 points, the eval prompt is still over-rewarding keyword density and needs further tuning.
