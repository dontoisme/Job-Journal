"""Rubrics, verdicts, and prompts, defined once.

Everything that decides how the quick screen judges a posting lives here so
it can be versioned and overridden from a file rather than restated in each
skill.

Adapted from the Pinloop CLI's approach (see docs/comparison-pinloop-cli.md):
a four-word verdict scale that is the model's own answer, a shipped prompt the
user can replace whole by storing a document under a fixed name, and profile
documents with reserved names whose absence is reported rather than hidden.
"""

from pathlib import Path
from typing import Any

from jj.config import JJ_HOME

# Bump by hand whenever any prompt or rubric text below changes. It is recorded
# on every judgment so analytics can segment by the rules that produced it.
PROMPT_VERSION = "2026-09-06.1"

# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------

#: The four words a verdict may be, worst to best. Order matters: a run can be
#: told to keep only postings at or above one of them.
VERDICTS: tuple[str, ...] = ("no", "weak", "fair", "strong")



def rank_of(verdict: str) -> int:
    """Where a verdict sits on the scale; -1 for anything that is not a verdict."""
    try:
        return VERDICTS.index((verdict or "").strip().lower())
    except ValueError:
        return -1


def at_or_above(verdict: str, keep: str) -> bool:
    """True when ``verdict`` is at or above ``keep`` on the scale."""
    return rank_of(verdict) >= rank_of(keep) >= 0


def drop_reason(verdict: str, keep: str) -> str:
    """Why a keep rule left a posting out, in the words a person reads."""
    return f"judged {verdict}, below {keep}"


# ---------------------------------------------------------------------------
# Profile documents with reserved names
# ---------------------------------------------------------------------------

#: name -> what the judge is told the document means. Stored as
#: ~/.job-journal/<name>.md. Missing ones are reported, never silently skipped.
PROFILE_DOCUMENTS: dict[str, str] = {
    "constraints": (
        "rules this person cannot break, such as work authorization, where they "
        "can be, compensation floor, and roles they will not take. If the posting "
        "breaks any rule written there, the verdict is `no`, whatever else is "
        "true, and the reasoning must name the rule it breaks."
    ),
    "preferences": "what this person wants and does not want in the next role.",
    "background": "what this person has done and can do, in their own words.",
}

#: What the screen could not do without each document, in the words a person reads.
_MISSING_EXPLANATIONS: dict[str, str] = {
    "constraints": "no constraints document is stored, so nothing could rule a posting out on its own",
    "preferences": "no preferences document is stored, so the model screened without being told what this person wants",
    "background": "no background document is stored, so the model screened on the corpus excerpt and profile only",
}


def profile_document_path(name: str) -> Path:
    """Where a reserved profile document lives."""
    return JJ_HOME / f"{name}.md"


def load_profile_documents() -> dict[str, Any]:
    """Read every reserved profile document that exists.

    Returns {"present": {name: text}, "missing": [name, ...]}. A document whose
    text is empty once whitespace is stripped counts as missing.
    """
    present: dict[str, str] = {}
    missing: list[str] = []
    for name in PROFILE_DOCUMENTS:
        path = profile_document_path(name)
        text = ""
        if path.exists():
            try:
                text = path.read_text(encoding="utf-8").strip()
            except OSError:
                text = ""
        if text:
            present[name] = text
        else:
            missing.append(name)
    return {"present": present, "missing": missing}


def describe_missing_documents(missing: list[str]) -> list[str]:
    """One line per missing document saying what could not be done."""
    return [_MISSING_EXPLANATIONS.get(name, f"no {name} document is stored") for name in missing]


# ---------------------------------------------------------------------------
# The quick screen prompt
# ---------------------------------------------------------------------------

QUICK_SCREEN_PROMPT_OVERRIDE = JJ_HOME / "quick-screen-prompt.md"

DEFAULT_QUICK_SCREEN_PROMPT = """You are screening job postings against one person, for a tool called Job Journal.

You get up to a hundred postings in this one message, and for each posting you see only the plain facts stored about it: a short reference, the job title, the employer, the location, the pay when any pay is stored, and the date it was first seen. You are not given the job description, so the requirements written in it are not in front of you. Screen on the facts you have and do not guess at what a description you cannot read might say. Your verdicts decide which of these postings get read properly later, description and all. So you are deciding what deserves a real look, not what deserves an application.

After the postings comes this person's profile: every document they keep, each labelled with the name it is stored under. Some names mean something fixed:

- constraints: rules this person cannot break, such as work authorization, where they can be, compensation floor, and roles they will not take. If a posting breaks a rule written there, its verdict is `no`, whatever else is true, and your reasoning must name the rule it breaks.
- preferences: what this person wants and does not want.
- background: what this person has done and can do.
- corpus: an excerpt of their resume corpus (roles and skills). Read it as part of their profile.

Give one verdict for every posting reference you were given, and for no other. A verdict is exactly one of these four words:

- `no`: a constraint is broken, or the posting has nothing to do with this person.
- `weak`: nothing rules it out, but the facts you can see point away from this person.
- `fair`: worth reading properly. The facts you can see line up, and the description would settle the rest.
- `strong`: the facts you can see line up well, and this looks like the kind of role this person is asking for.

`fair` means "worth a real look", not "apply to this one". What settles that is the job description, and you have not read it.

With each verdict give one or two sentences of reasoning, written for this person to read, saying what drove it. Grade honestly: a screen that calls everything strong has told this person nothing.

Answer for every posting reference you were given, including the ones whose facts are thin. A posting you say nothing about is reported to this person as one that could not be screened.

Do not use any tools. Answer with a JSON array and nothing else, no prose before or after it, in exactly this shape:

[{"ref": "L1", "verdict": "fair", "reasoning": "..."}, ...]
"""


def load_quick_screen_prompt() -> tuple[str, str]:
    """The quick screen instructions and where they came from.

    Returns (text, source) where source is "shipped" or the override path. A
    stored override whose text is empty once whitespace is stripped counts as
    no override at all.
    """
    if QUICK_SCREEN_PROMPT_OVERRIDE.exists():
        try:
            text = QUICK_SCREEN_PROMPT_OVERRIDE.read_text(encoding="utf-8")
        except OSError:
            text = ""
        if text.strip():
            return text, str(QUICK_SCREEN_PROMPT_OVERRIDE)
    return DEFAULT_QUICK_SCREEN_PROMPT, "shipped"
