#!/usr/bin/env python3
"""A/B validation: compare Sonnet vs Opus on the pipeline final resume eval.

One-off harness (NOT scheduled). Before committing the Slack [Go] pipeline to
Sonnet for the resume-eval phases, run this to confirm Sonnet scores stay
within tolerance of Opus on real historical resumes.

It re-runs `/resume-eval <app_id> --final` under each model via `claude -p`,
parses the printed `Final Score:` line from stdout, and reports the deltas.

Caveat: `/resume-eval --final` writes to the pipeline_runs row each run, so the
last model run leaves its score in the DB. This harness reads scores from
stdout (not the DB), so that overwrite does not affect the comparison — but run
it when no live pipeline is mid-flight for the same apps.

Usage:
    python scripts/eval_ab.py                 # auto-pick up to 10 historical apps
    python scripts/eval_ab.py --limit 6
    python scripts/eval_ab.py --apps 1421,1455 --models sonnet,opus
"""
import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jj.db import get_connection  # noqa: E402

ALLOWED_TOOLS = "Bash,WebFetch,WebSearch,Read,Write,Grep,Glob"
TIMEOUT_SEC = 300
TOLERANCE = 5  # points; Sonnet is "within tolerance" if mean abs delta < this
SCORE_RE = re.compile(r"Final Score:\s*(\d+)", re.IGNORECASE)


def pick_apps(limit: int) -> list[int]:
    """App IDs whose pipeline_run has a Phase-2 eval (most recent first)."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT application_id, MAX(id) AS rid
            FROM pipeline_runs
            WHERE eval_score_strict IS NOT NULL
            GROUP BY application_id
            ORDER BY rid DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [r["application_id"] for r in rows]


def run_eval(app_id: int, model: str) -> int | None:
    """Run /resume-eval --final under one model; return parsed Final Score."""
    claude = shutil.which("claude")
    if not claude:
        print("ERROR: 'claude' not found in PATH", file=sys.stderr)
        sys.exit(127)
    cmd = [
        claude, "-p", f"/resume-eval {app_id} --final",
        "--allowedTools", ALLOWED_TOOLS, "--model", model,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_SEC)
    except subprocess.TimeoutExpired:
        print(f"  [{model}] app {app_id}: TIMEOUT", file=sys.stderr)
        return None
    m = SCORE_RE.search(proc.stdout or "")
    if not m:
        print(f"  [{model}] app {app_id}: no score parsed (rc={proc.returncode})",
              file=sys.stderr)
        return None
    return int(m.group(1))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--apps", type=str, default="",
                    help="comma-separated app IDs (overrides auto-pick)")
    ap.add_argument("--models", type=str, default="sonnet,opus")
    args = ap.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    if len(models) != 2:
        print("Need exactly two --models to compare, e.g. sonnet,opus", file=sys.stderr)
        return 2

    if args.apps:
        app_ids = [int(x) for x in args.apps.split(",") if x.strip()]
    else:
        app_ids = pick_apps(args.limit)
    if not app_ids:
        print("No historical pipeline_runs with an eval score to compare.")
        return 1

    print(f"Comparing {models[0]} vs {models[1]} on {len(app_ids)} app(s)\n")
    header = f"{'app':>6}  {models[0]:>8}  {models[1]:>8}  {'delta':>6}"
    print(header)
    print("-" * len(header))

    deltas: list[int] = []
    for app_id in app_ids:
        a = run_eval(app_id, models[0])
        b = run_eval(app_id, models[1])
        if a is None or b is None:
            print(f"{app_id:>6}  {str(a):>8}  {str(b):>8}  {'--':>6}")
            continue
        d = a - b
        deltas.append(abs(d))
        print(f"{app_id:>6}  {a:>8}  {b:>8}  {d:>+6}")

    if not deltas:
        print("\nNo comparable pairs produced a score.")
        return 1

    mean_abs = sum(deltas) / len(deltas)
    within = sum(1 for d in deltas if d <= TOLERANCE)
    print("\nSummary:")
    print(f"  pairs scored        : {len(deltas)}")
    print(f"  mean |delta|        : {mean_abs:.1f} pts")
    print(f"  max  |delta|        : {max(deltas)} pts")
    print(f"  within +/-{TOLERANCE} pts     : {within}/{len(deltas)}")
    verdict = ("PASS — keep Sonnet" if mean_abs < TOLERANCE
               else "FAIL — set pipeline.eval_model: opus in config.yaml")
    print(f"  verdict             : {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
