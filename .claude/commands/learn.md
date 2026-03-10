# /learn — Update CLAUDE.md with a lesson

Use this immediately after Claude makes a mistake or you spot a recurring pattern worth encoding.

## Instructions

1. Review the recent conversation to identify what went wrong or what pattern should be remembered.

2. Formulate a single, crisp, imperative rule. Good rules are:
   - Specific (not "be careful with Firebase" but "always attach error callbacks to onSnapshot calls for offline resilience")
   - Actionable (tells Claude exactly what to do or not do)
   - Scoped (project-specific rules go in this repo's CLAUDE.md; cross-project rules go in ~/Projects/CLAUDE.md)

3. Determine the right file:
   - Specific to this project → `CLAUDE.md` in this repo
   - General TypeScript / Firebase / architecture patterns → `~/Projects/CLAUDE.md`

4. Append the rule as a bullet under the `## Lessons Learned` section in the appropriate file. Include today's date in YYYY-MM-DD format. If the section doesn't exist yet, add it near the bottom of the file.

5. Confirm to the user: "Added to [filename]: [the rule]"

## Example output

```
Added to Squabble/CLAUDE.md:
- (2026-02-23) Always run firebase emulators before integration tests — the test suite does not auto-start them.
```
