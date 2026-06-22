# Job-Journal Pipeline Architecture: v1.2 Refinement

**Source:** Lattice Staff PM, AI application — second pipeline run after v1.1 feedback was incorporated. Defects partially addressed (no Lattice-name editorializing, no grammar collapse), but new defects surfaced and the structural problem with auto-selection became clearer.

**Companion to:** `pipeline-refinement-notes.md` (v1.1 feedback). This document supersedes the auto-selection logic guidance in that doc and adds new findings.

---

## Headline change: keep the pipeline, kill the auto-selection

The pipeline currently produces multiple variants (strict, disciplined, freeform, refined), scores them, and selects the highest-scored variant as the "winner." This auto-selection logic is the dominant failure mode.

Across three runs (OpenAI, Lattice v1, Lattice v2), the pipeline has consistently auto-selected variants that read worse to a human reviewer than alternatives the pipeline produced and discarded. The variants themselves are doing useful work. The layer choosing between them is broken.

**Recommended change:** the pipeline should produce variants and present all of them. It should not select. The human picks based on target context.

---

## Why "just use freeform every time" is the wrong conclusion

Freeform has won every recent run. The instinct to simplify the pipeline to "freeform only" is wrong, for two reasons:

1. **Freeform is winning by default, not by design.** Disciplined-mode bugs (em-dash → semicolon substitution in v1.1, slug-formatted skills labels in v1.2) are degrading disciplined output. When those bugs are fixed, disciplined should win for most senior-tier applications. Freeform is currently winning because its competition is broken.

2. **Different targets need different variants.** A high-volume mid-level role at a small startup may genuinely benefit from the refined variant's keyword density. A senior role at an AI-savvy company will reject anything that reads as JD-mirroring. There is no single "best" variant — there's a slate of strategically distinct variants, and the right one depends on context the pipeline can't always infer from the JD alone.

Optimizing for "always pick freeform" eliminates a useful signal. Optimizing for "produce variants and let the human pick" preserves it.

---

## What each variant is actually for

The pipeline currently produces four variants. Each catches a different failure mode:

| Variant | What it catches | When it should win |
|---------|----------------|---------------------|
| **Strict** | "Did the corpus support this claim at all" | Sanity check / regression baseline. Should rarely be the submission. |
| **Disciplined** | "Is the structure right" | Currently broken. When fixed, should win most senior-tier applications. |
| **Freeform** | "Does the prose read like a person wrote it" | High-prestige or AI-savvy targets where over-tailoring tells are fatal. |
| **Refined** | "Did we maximize JD keyword density" | Currently broken. Speculative use case: high-volume mid-level applications where ATS keyword match matters and human reviewers won't pattern-match for AI tells. |

The variants are not redundant. They're optimized for different target audiences. The pipeline's job is to generate them; the human's job is to pick.

---

## Specific defects in v1.2 run

### Defect 1: Disciplined skills section renders slug-formatted labels

The Lattice v2 disciplined output rendered:

```
ai-&-orchestration: Agentic AI, LLM Integration...
product-management: Product Strategy...
analytics-&-tools: Amplitude, Mixpanel...
```

Lowercase, kebab-case, hyphenated category labels. These appear to be slug/key names from the corpus YAML, not display names. The freeform/strict variants render correctly with title-cased display names (`AI & Machine Learning`, `Product Strategy`).

This is a disciplined-mode-specific rendering bug. A recruiter seeing slug-formatted labels will read the document as broken or copy-pasted incorrectly. The variant is non-submittable in this state.

The integrity audit did not catch this because the audit checks content (em-dashes, dates, duplicates) but not rendering (label formatting, character set, capitalization).

### Defect 2: Freeform/strict variants produced byte-identical output

The freeform and strict PDFs in the v1.2 run are essentially identical aside from header padding. This shouldn't happen if the modes are differentiated. Either:

- The strict path silently fell back to freeform mode
- The pipeline produces both variants from the same source and only renames them
- Both modes converged on the same output by coincidence (unlikely given different prompt scaffolding)

Worth checking pipeline logs to confirm `mode="strict"` actually ran the strict-mode code path. If strict is silently falling back, the variant slate is producing two effectively-identical outputs and one differentiated one, which reduces the value of generating multiple variants.

### Defect 3: Summary integrity flag (recurring)

The disciplined summary states:

> "Active builder shipping production code with Claude Code as a first-class collaborator across discovery, specs, and ship."

This frames a personal-projects behavior (Squabble Inn, job-journal) as a current professional behavior in the consulting role. Same flag as flagged in the prior conversation — the line is defensible only if the candidate can answer "tell me about a feature you shipped to production with Claude Code in your consulting role" in the screen.

This is not a pipeline bug per se, but the pipeline is producing this line repeatedly because it has high JD-keyword density and the summary generation has no fact-grounding check against role context. Worth adding: summary claims must be supportable by at least one corpus bullet from the role being described.

---

## Recommended pipeline architecture

### Current shape (v1.1)

```
Phase 1: Generate variants (strict + disciplined + freeform + refined)
Phase 2: Score each with Opus eval
Phase 3: Refinement pass on highest-scored variant
Phase 4: Re-score refined variant
Phase 5: Auto-select highest-scored final variant → Slack
```

### Proposed shape (v1.2)

```
Phase 1: Generate three variants in parallel (strict + disciplined + freeform)
Phase 2: Run integrity audit on each (Python-layer, fail-closed per v1.1 spec)
Phase 3: Score each with Opus eval (with over-tailoring penalty applied per v1.1)
Phase 4: Present all three variants in Slack with:
  - Fit score
  - One-line "this version optimizes for X" summary
  - Audit pass/fail status
  - Direct links to all three PDFs
Phase 5: Human picks. No auto-selection.
```

Key changes:

1. **Refinement phase removed.** It has consistently produced worse output than its input. Cutting it removes the dominant failure mode and saves a generation pass.
2. **Auto-selection removed.** Replaced by human pick. The cognitive load is bounded (three options) and the human has context the pipeline doesn't (target tier, audience savvy, application strategy).
3. **Variant slate stays at three.** Strict for control/baseline, disciplined for most submissions once bugs are fixed, freeform for high-prestige targets.

### Optional: refinement as a fourth variant, not a phase

If there's reason to keep refinement available (e.g., for high-volume mid-level applications where keyword density genuinely helps), reframe it as a fourth variant rather than a sequential refinement phase. Generate it in parallel with the others, score it with the over-tailoring penalty applied, present it alongside. Most runs it'll come in last and the human will ignore it. Occasionally it'll be the right answer for a specific target.

This preserves the option without making refinement the default path.

---

## Why removing auto-selection matters beyond this run

The variants are currently producing useful signal that the pipeline is hiding. When auto-selection picks "the highest-scored" version, the human only sees the winner. That means:

- Disciplined-mode bugs are invisible because the auto-selection routes around them (picks freeform instead)
- Refinement over-tailoring is invisible because the user only sees the refined output, not the freeform input it degraded from
- Differential quality across variants becomes hard to diagnose

Removing auto-selection makes variant differences visible. Visibility lets you (the human) debug pipeline issues faster, because you can see when disciplined produces something better than freeform — which is the signal that disciplined is working as intended.

In other words: auto-selection is masking the development feedback loop you need to actually improve the pipeline.

---

## Bug fixes needed before v1.2 ships

These should ship together with the architectural change above. They're separable in principle but bundling them is the right move.

### 1. Skills section rendering bug (Defect 1)

Disciplined-mode skills section is rendering raw YAML keys instead of display labels. Either:

- Fix the disciplined-mode template to look up display names from a labels map
- Add a corpus convention that category keys ARE the display names (no slug-style keys allowed)
- Add an integrity audit check: skill section labels must match `^[A-Z][A-Za-z0-9 &]+$` pattern, fail closed if any label contains hyphens or lowercase initial characters

The third option is the cheapest and catches future regressions of the same pattern.

### 2. Em-dash replacement strategy (carryover from v1.1)

Em-dash → semicolon substitution produces grammatically broken bullets when the em-dash was used parenthetically rather than to join independent clauses. Two options:

- Default replacement to colon, not semicolon (works in more contexts)
- Don't auto-replace; fail the audit and force regeneration with explicit "no em-dashes" constraint

Either is fine. Latter is more conservative and probably correct given that em-dashes in the corpus likely indicate the corpus itself needs lint cleanup.

### 3. Strict/freeform variant differentiation (Defect 2)

Verify the strict path is actually running strict-mode code. If both paths produce identical output, either:

- Mode flag isn't being respected
- Strict mode is failing silently and falling back to freeform
- Both modes converge on the same output for this corpus shape (worth confirming explicitly)

### 4. Summary fact-grounding check

Summary claims about current behavior should be supportable by at least one corpus bullet from the role being described. Add as integrity audit check:

```
For each factual claim in the summary that names a current behavior:
  Verify at least one corpus bullet from the most recent role supports the claim.
  If no support found, flag for human review.
```

This is fuzzier than the other audit checks but catches the recurring "Claude Code as first-class collaborator" issue.

---

## Implementation priority

1. **High:** Remove auto-selection. Present variants to human. Largest single architectural improvement.
2. **High:** Fix disciplined-mode skills rendering bug. Disqualifies disciplined output until fixed.
3. **Medium:** Add over-tailoring penalty to eval prompts (carryover from v1.1, still not implemented).
4. **Medium:** Remove refinement phase OR demote to optional fourth variant. Either is fine; cutting is simpler.
5. **Low:** Em-dash replacement strategy fix. Hasn't bitten in v1.2 but will recur eventually.
6. **Low:** Summary fact-grounding check. Catches the recurring summary integrity flag.

---

## Test cases for v1.2 validation

After implementing the architectural change:

1. Run the pipeline against the Lattice JD again. Confirm three variants produced, all delivered to Slack, no auto-selection occurred.
2. Confirm disciplined skills section renders with title-cased display labels matching freeform format.
3. Confirm freeform and strict variants produce *different* output (or document why they don't for this corpus).
4. Confirm refinement phase is either removed entirely or producing a parallel fourth variant rather than overwriting the freeform output.
5. Confirm Slack message shows all variants with scores and one-line summaries, allowing human selection.

If after these changes the pipeline still produces freeform as the obvious-best variant for senior/AI-savvy targets, that's the right outcome — but it's a *human-observable* outcome rather than an auto-selection outcome. The pipeline becomes a tool for producing options, not a tool for making decisions.

---

## Meta-note

The progression across v1.0 → v1.1 → v1.2 has followed a consistent pattern: each version moves more decision-making from the pipeline to the human, and each version improves output quality. The pipeline is best as a generation tool, not a selection tool. Future revisions should preserve this direction.

The single highest-leverage move available right now is removing auto-selection. Everything else is incremental.
