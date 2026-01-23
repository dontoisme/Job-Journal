"""Job Journal CLI - Main entry point."""

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from jj import __version__
from jj.db import init_database, get_stats
from jj.config import (
    JJ_HOME,
    ensure_jj_home,
    load_profile,
    save_profile,
    load_config,
    save_config,
    DEFAULT_PROFILE,
    DEFAULT_CONFIG,
)

app = typer.Typer(
    name="jj",
    help="Job Journal - Interview your career, customize your resume.",
    no_args_is_help=True,
)
console = Console()


def version_callback(value: bool):
    if value:
        console.print(f"Job Journal v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        None, "--version", "-v", callback=version_callback, is_eager=True,
        help="Show version and exit."
    ),
):
    """Job Journal - Interview your career, customize your resume."""
    pass


@app.command()
def init(
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing installation"),
):
    """Initialize Job Journal (~/.job-journal/)."""

    if JJ_HOME.exists() and not force:
        console.print(f"[yellow]Job Journal already initialized at {JJ_HOME}[/yellow]")
        console.print("Use --force to reinitialize (will preserve your data).")

        # Check for existing .job-apply/ to offer migration
        job_apply_path = Path.home() / ".job-apply"
        if job_apply_path.exists():
            console.print()
            console.print("[cyan]Found existing ~/.job-apply/ directory![/cyan]")
            if Confirm.ask("Would you like to migrate your data?"):
                _migrate_from_job_apply(job_apply_path)
        return

    console.print(Panel.fit(
        "[bold green]Welcome to Job Journal![/bold green]\n\n"
        "Let's set up your career documentation system.",
        title="Job Journal",
    ))

    # Create directory structure
    ensure_jj_home()

    # Initialize database
    init_database()

    # Collect basic profile info
    console.print("\n[bold]Let's set up your profile:[/bold]\n")

    profile = DEFAULT_PROFILE.copy()

    profile["name"]["first"] = Prompt.ask("First name")
    profile["name"]["last"] = Prompt.ask("Last name")
    profile["contact"]["email"] = Prompt.ask("Email")
    profile["contact"]["phone"] = Prompt.ask("Phone", default="")
    profile["contact"]["location"] = Prompt.ask("Location (City, State)", default="")
    profile["links"]["linkedin"] = Prompt.ask("LinkedIn URL", default="")

    save_profile(profile)
    save_config(DEFAULT_CONFIG)

    console.print()
    console.print(Panel.fit(
        f"[green]Job Journal initialized at {JJ_HOME}[/green]\n\n"
        "Next steps:\n"
        "  [cyan]jj interview[/cyan]     - Build your corpus through conversation\n"
        "  [cyan]jj import base[/cyan]   - Import existing base.md file\n"
        "  [cyan]jj corpus[/cyan]        - View/edit your corpus",
        title="Setup Complete",
    ))


def _migrate_from_job_apply(source: Path):
    """Migrate data from existing ~/.job-apply/ installation."""
    console.print("\n[bold]Migrating from ~/.job-apply/...[/bold]\n")

    # Check for importable files
    files_found = []

    base_md = source / "resume" / "base.md"
    if base_md.exists():
        files_found.append(("base.md", base_md))

    profile_yaml = source / "profile.yaml"
    if profile_yaml.exists():
        files_found.append(("profile.yaml", profile_yaml))

    config_yaml = source / "config.yaml"
    if config_yaml.exists():
        files_found.append(("config.yaml", config_yaml))

    applications_csv = source / "applications.csv"
    if applications_csv.exists():
        files_found.append(("applications.csv", applications_csv))

    prospects_csv = source / "prospects.csv"
    if prospects_csv.exists():
        files_found.append(("prospects.csv", prospects_csv))

    if not files_found:
        console.print("[yellow]No files found to migrate.[/yellow]")
        return

    console.print("Found files to migrate:")
    for name, path in files_found:
        console.print(f"  - {name}")

    if not Confirm.ask("\nProceed with migration?"):
        return

    # Ensure JJ home exists
    ensure_jj_home()
    init_database()

    # Copy/import files
    import shutil

    for name, path in files_found:
        if name == "base.md":
            # Import base.md into database
            console.print(f"  Importing {name}...")
            from jj.parser import import_base_md
            stats = import_base_md(path)
            console.print(f"    Imported {stats['roles']} roles, {stats['entries']} entries")
        elif name in ("profile.yaml", "config.yaml"):
            # Copy YAML files
            dest = JJ_HOME / name
            shutil.copy(path, dest)
            console.print(f"  Copied {name}")
        elif name in ("applications.csv", "prospects.csv"):
            # Copy CSV files
            dest = JJ_HOME / name
            shutil.copy(path, dest)
            console.print(f"  Copied {name}")

    console.print("\n[green]Migration complete![/green]")
    console.print("Your original ~/.job-apply/ has been preserved.")


@app.command()
def interview(
    role: Optional[str] = typer.Argument(None, help="Specific role to deep-dive on"),
):
    """Start or continue an interview session to build your corpus."""

    if not JJ_HOME.exists():
        console.print("[red]Job Journal not initialized. Run 'jj init' first.[/red]")
        raise typer.Exit(1)

    console.print(Panel.fit(
        "[bold]Interview Mode[/bold]\n\n"
        "This command is designed to be run with Claude Code.\n"
        "Use the [cyan]/interview[/cyan] slash command for the full experience.",
        title="Interview",
    ))

    # For now, just show stats and prompt to use Claude Code
    stats = get_stats()
    console.print(f"\nYour corpus: {stats['entries']} entries across {stats['roles']} roles")

    if stats['roles'] == 0:
        console.print("\n[yellow]No roles yet. Start with '/interview' in Claude Code.[/yellow]")
    elif role:
        console.print(f"\nTo deep-dive on '{role}', use '/interview {role}' in Claude Code.")


# =============================================================================
# Corpus Commands
# =============================================================================

corpus_app = typer.Typer(
    name="corpus",
    help="Manage your resume corpus (entries, sync, search).",
    no_args_is_help=True,
)
app.add_typer(corpus_app, name="corpus")


@corpus_app.command("sync")
def corpus_sync(
    path: Optional[Path] = typer.Option(None, "--path", "-p", help="Path to base.md file"),
    replace: bool = typer.Option(False, "--replace", "-r", help="Replace existing entries from base.md"),
):
    """Sync corpus entries from base.md file.

    Parses base.md and imports/updates entries in the database with
    line-number tracking for round-trip validation.

    Examples:
        jj corpus sync
        jj corpus sync --path ~/custom/base.md
        jj corpus sync --replace
    """
    if not JJ_HOME.exists():
        console.print("[red]Job Journal not initialized. Run 'jj init' first.[/red]")
        raise typer.Exit(1)

    from jj.corpus import sync_from_base_md, DEFAULT_BASE_MD

    base_path = path or DEFAULT_BASE_MD

    if not base_path.exists():
        console.print(f"[red]File not found: {base_path}[/red]")
        raise typer.Exit(1)

    console.print(f"[bold]Syncing corpus from {base_path}...[/bold]\n")

    result = sync_from_base_md(path=base_path, replace=replace)

    if result.errors:
        for error in result.errors:
            console.print(f"[red]Error: {error}[/red]")
        raise typer.Exit(1)

    console.print(Panel.fit(
        f"[green]{result}[/green]\n\n"
        f"Entries added: {result.entries_added}\n"
        f"Entries updated: {result.entries_updated}\n"
        f"Entries deleted: {result.entries_deleted}\n"
        f"Roles added: {result.roles_added}\n"
        f"Roles updated: {result.roles_updated}",
        title="Corpus Sync Complete",
    ))


@corpus_app.command("list")
def corpus_list(
    tags: Optional[str] = typer.Option(None, "--tags", "-t", help="Filter by tags (comma-separated)"),
    role: Optional[str] = typer.Option(None, "--role", "-r", help="Filter by role/company"),
    category: Optional[str] = typer.Option(None, "--category", "-c", help="Filter by category"),
    limit: int = typer.Option(50, "--limit", "-l", help="Maximum entries to show"),
):
    """List corpus entries with optional filtering.

    Examples:
        jj corpus list
        jj corpus list --tags growth,ai
        jj corpus list --category leadership
    """
    if not JJ_HOME.exists():
        console.print("[red]Job Journal not initialized. Run 'jj init' first.[/red]")
        raise typer.Exit(1)

    from jj.corpus import search_corpus

    tag_list = [t.strip() for t in tags.split(",")] if tags else None

    entries = search_corpus(
        tags=tag_list,
        category=category,
    )[:limit]

    if not entries:
        console.print("[yellow]No entries found matching your criteria.[/yellow]")
        return

    from rich.table import Table

    table = Table(title=f"Corpus Entries ({len(entries)} shown)")
    table.add_column("ID", style="dim", width=4)
    table.add_column("Role", width=20)
    table.add_column("Category", width=12)
    table.add_column("Bullet", width=60)
    table.add_column("Used", width=4)

    for entry in entries:
        role_str = f"{entry.get('role_title', '')} @ {entry.get('company', '')}"
        if len(role_str) > 20:
            role_str = role_str[:17] + "..."

        bullet = entry["text"]
        if len(bullet) > 60:
            bullet = bullet[:57] + "..."

        table.add_row(
            str(entry["id"]),
            role_str,
            entry.get("category") or "-",
            bullet,
            str(entry.get("times_used", 0)),
        )

    console.print(table)


@corpus_app.command("search")
def corpus_search(
    query: str = typer.Argument(..., help="Text to search for"),
    limit: int = typer.Option(20, "--limit", "-l", help="Maximum results"),
):
    """Search corpus entries by text content.

    Examples:
        jj corpus search "growth"
        jj corpus search "conversion rate" --limit 10
    """
    if not JJ_HOME.exists():
        console.print("[red]Job Journal not initialized. Run 'jj init' first.[/red]")
        raise typer.Exit(1)

    from jj.corpus import search_corpus

    entries = search_corpus(query=query)[:limit]

    if not entries:
        console.print(f"[yellow]No entries found matching '{query}'.[/yellow]")
        return

    console.print(f"[bold]Found {len(entries)} entries matching '{query}':[/bold]\n")

    for entry in entries:
        console.print(f"[cyan]{entry.get('company', 'Unknown')}[/cyan] - {entry.get('role_title', 'Unknown')}")
        console.print(f"  {entry['text']}")
        console.print()


@corpus_app.command("stats")
def corpus_stats():
    """Show corpus statistics."""
    if not JJ_HOME.exists():
        console.print("[red]Job Journal not initialized. Run 'jj init' first.[/red]")
        raise typer.Exit(1)

    from jj.corpus import get_corpus_stats

    stats = get_corpus_stats()

    console.print(Panel.fit(
        f"[bold]Corpus Statistics[/bold]\n\n"
        f"Total Entries: {stats['total_entries']}\n"
        f"Total Roles: {stats['total_roles']}\n\n"
        f"[bold]By Source:[/bold]\n" +
        "\n".join(f"  {k}: {v}" for k, v in stats['by_source'].items()) + "\n\n"
        f"[bold]By Category:[/bold]\n" +
        "\n".join(f"  {k}: {v}" for k, v in list(stats['by_category'].items())[:10]),
        title="Corpus Stats",
    ))


@corpus_app.command("suggestions")
def corpus_suggestions(
    status: str = typer.Option("pending", "--status", "-s", help="Filter by status: pending, accepted, dismissed"),
    limit: int = typer.Option(20, "--limit", "-l", help="Maximum suggestions to show"),
):
    """View corpus improvement suggestions.

    Suggestions are generated when:
    - Importing resumes with unmatched bullets
    - Generating resumes with JD gap analysis

    Examples:
        jj corpus suggestions
        jj corpus suggestions --status pending
    """
    if not JJ_HOME.exists():
        console.print("[red]Job Journal not initialized. Run 'jj init' first.[/red]")
        raise typer.Exit(1)

    from jj.db import get_corpus_suggestions

    suggestions = get_corpus_suggestions(status=status, limit=limit)

    if not suggestions:
        console.print(f"[yellow]No {status} suggestions found.[/yellow]")
        return

    console.print(f"[bold]{len(suggestions)} {status} suggestions:[/bold]\n")

    for s in suggestions:
        type_color = {
            "missing_theme": "yellow",
            "missing_keyword": "cyan",
            "weak_coverage": "magenta",
            "unmatched_bullet": "red",
        }.get(s["gap_type"], "white")

        console.print(f"[{type_color}][{s['gap_type'].upper()}][/{type_color}] {s['theme']}")
        console.print(f"  {s['suggestion'][:200]}")
        if s.get("suggested_company"):
            console.print(f"  [dim]Suggested role: {s['suggested_role_title']} @ {s['suggested_company']}[/dim]")
        console.print()


@corpus_app.command("dismiss")
def corpus_dismiss(
    suggestion_id: Optional[int] = typer.Option(None, "--id", help="Dismiss a specific suggestion by ID"),
    theme: Optional[str] = typer.Option(None, "--theme", help="Dismiss all suggestions for a theme"),
):
    """Dismiss corpus suggestions.

    Examples:
        jj corpus dismiss --id 5
        jj corpus dismiss --theme "stakeholder management"
    """
    if not JJ_HOME.exists():
        console.print("[red]Job Journal not initialized. Run 'jj init' first.[/red]")
        raise typer.Exit(1)

    from jj.db import update_corpus_suggestion_status, dismiss_corpus_suggestions_for_theme

    if suggestion_id:
        if update_corpus_suggestion_status(suggestion_id, "dismissed"):
            console.print(f"[green]Dismissed suggestion {suggestion_id}[/green]")
        else:
            console.print(f"[red]Suggestion {suggestion_id} not found[/red]")
    elif theme:
        count = dismiss_corpus_suggestions_for_theme(theme)
        console.print(f"[green]Dismissed {count} suggestions for theme '{theme}'[/green]")
    else:
        console.print("[red]Provide either --id or --theme[/red]")
        raise typer.Exit(1)


@corpus_app.command("edit")
def corpus_edit():
    """Open corpus.md in your default editor."""
    if not JJ_HOME.exists():
        console.print("[red]Job Journal not initialized. Run 'jj init' first.[/red]")
        raise typer.Exit(1)

    corpus_path = JJ_HOME / "corpus.md"

    import os
    editor = os.environ.get("EDITOR", "vim")
    os.system(f'{editor} "{corpus_path}"')


@app.command("import")
def import_cmd():
    """Import data from external sources."""
    console.print("Use one of the import subcommands:")
    console.print("  jj import-base <file>  - Import a base.md file")


@app.command("import-base")
def import_base(
    file: Path = typer.Argument(..., help="Path to base.md file to import"),
):
    """Import an existing base.md file into your corpus."""

    if not JJ_HOME.exists():
        console.print("[red]Job Journal not initialized. Run 'jj init' first.[/red]")
        raise typer.Exit(1)

    if not file.exists():
        console.print(f"[red]File not found: {file}[/red]")
        raise typer.Exit(1)

    console.print(f"Importing {file}...")

    from jj.parser import import_base_md
    stats = import_base_md(file)

    console.print(Panel.fit(
        f"[green]Import complete![/green]\n\n"
        f"Roles: {stats['roles']}\n"
        f"Entries: {stats['entries']}\n"
        f"Skills: {stats['skills']}",
        title="Import Results",
    ))


# =============================================================================
# Resume Commands
# =============================================================================

resume_app = typer.Typer(
    name="resume",
    help="Generate and manage resumes with corpus validation.",
    no_args_is_help=True,
)
app.add_typer(resume_app, name="resume")


@resume_app.command("list")
def resume_list(
    variant: Optional[str] = typer.Option(None, "--variant", "-v", help="Filter by variant"),
    company: Optional[str] = typer.Option(None, "--company", "-c", help="Filter by company"),
    limit: int = typer.Option(20, "--limit", "-l", help="Maximum resumes to show"),
):
    """List generated resumes.

    Examples:
        jj resume list
        jj resume list --variant growth
        jj resume list --company "ZenBusiness"
    """
    if not JJ_HOME.exists():
        console.print("[red]Job Journal not initialized. Run 'jj init' first.[/red]")
        raise typer.Exit(1)

    from jj.resume_gen import list_resumes

    resumes = list_resumes(variant=variant, company=company, limit=limit)

    if not resumes:
        console.print("[yellow]No resumes found.[/yellow]")
        return

    from rich.table import Table

    table = Table(title=f"Resumes ({len(resumes)} shown)")
    table.add_column("ID", style="dim", width=4)
    table.add_column("Filename", width=40)
    table.add_column("Variant", width=12)
    table.add_column("Company", width=15)
    table.add_column("Entries", width=7)
    table.add_column("Valid", width=5)
    table.add_column("Created", width=10)

    for r in resumes:
        filename = r["filename"]
        if len(filename) > 40:
            filename = filename[:37] + "..."

        valid_str = "[green]Yes[/green]" if r.get("is_valid") else "[red]No[/red]"
        created = r.get("created_at", "")[:10] if r.get("created_at") else "-"

        table.add_row(
            str(r["id"]),
            filename,
            r.get("variant") or "-",
            (r.get("target_company") or "-")[:15],
            str(r.get("entry_count", 0)),
            valid_str,
            created,
        )

    console.print(table)


@resume_app.command("show")
def resume_show(
    resume_id: int = typer.Argument(..., help="Resume ID to show"),
):
    """Show details of a specific resume including entries used.

    Examples:
        jj resume show 1
    """
    if not JJ_HOME.exists():
        console.print("[red]Job Journal not initialized. Run 'jj init' first.[/red]")
        raise typer.Exit(1)

    from jj.resume_gen import get_resume_details

    details = get_resume_details(resume_id)

    if not details:
        console.print(f"[red]Resume {resume_id} not found.[/red]")
        raise typer.Exit(1)

    # Basic info
    console.print(Panel.fit(
        f"[bold]{details['filename']}[/bold]\n\n"
        f"Variant: {details.get('variant') or 'general'}\n"
        f"Company: {details.get('target_company') or '-'}\n"
        f"Role: {details.get('target_role') or '-'}\n"
        f"JD URL: {details.get('jd_url') or '-'}\n"
        f"Valid: {'Yes' if details.get('is_valid') else 'No'}\n"
        f"Drift Score: {details.get('drift_score', 0)}\n"
        f"Created: {details.get('created_at', '-')}",
        title=f"Resume #{resume_id}",
    ))

    # Show entries
    entries = details.get("entries", [])
    if entries:
        console.print(f"\n[bold]Entries Used ({len(entries)}):[/bold]\n")

        current_role = None
        for entry in entries:
            role_key = f"{entry.get('role_title')} @ {entry.get('role_company')}"
            if role_key != current_role:
                current_role = role_key
                console.print(f"\n[cyan]{role_key}[/cyan]")

            console.print(f"  - {entry['text'][:100]}...")

    # Show sections
    sections = details.get("sections", [])
    if sections:
        console.print(f"\n[bold]Sections ({len(sections)}):[/bold]")
        for section in sections:
            console.print(f"  - {section['section_type']}: {section.get('section_name') or 'default'}")


@resume_app.command("import")
def resume_import_cmd(
    path: Path = typer.Argument(..., help="Path to resume file or directory"),
    threshold: float = typer.Option(0.85, "--threshold", "-t", help="Match threshold (0-1)"),
    recursive: bool = typer.Option(True, "--recursive/--no-recursive", help="Recurse into subdirectories"),
):
    """Import existing resumes and link to corpus.

    Parses PDF/DOCX files, extracts bullets, and matches them to
    corpus entries. Unmatched bullets become corpus suggestions.

    Examples:
        jj resume import ~/Documents/Resumes/my-resume.pdf
        jj resume import "~/Downloads/Resumes - Organized/Submitted/2026/"
    """
    if not JJ_HOME.exists():
        console.print("[red]Job Journal not initialized. Run 'jj init' first.[/red]")
        raise typer.Exit(1)

    from jj.resume_import import import_resume, import_directory, get_import_summary

    if not path.exists():
        console.print(f"[red]Path not found: {path}[/red]")
        raise typer.Exit(1)

    if path.is_file():
        console.print(f"[bold]Importing {path.name}...[/bold]\n")
        result = import_resume(path, match_threshold=threshold)

        if result.error:
            console.print(f"[red]Error: {result.error}[/red]")
            raise typer.Exit(1)

        if result.skipped:
            console.print(f"[yellow]Skipped (already imported): {path.name}[/yellow]")
        else:
            console.print(Panel.fit(
                f"[green]Imported successfully![/green]\n\n"
                f"Resume ID: {result.resume_id}\n"
                f"Entries linked: {result.entries_linked}\n"
                f"Unmatched bullets: {result.entries_unmatched}",
                title="Import Result",
            ))

            if result.unmatched_bullets:
                console.print("\n[yellow]Unmatched bullets (created as suggestions):[/yellow]")
                for bullet in result.unmatched_bullets[:5]:
                    console.print(f"  - {bullet[:80]}...")
                if len(result.unmatched_bullets) > 5:
                    console.print(f"  ... and {len(result.unmatched_bullets) - 5} more")

    else:
        console.print(f"[bold]Importing resumes from {path}...[/bold]\n")
        results = import_directory(path, recursive=recursive, match_threshold=threshold)

        summary = get_import_summary(results)

        console.print(Panel.fit(
            f"[green]Import complete![/green]\n\n"
            f"Files processed: {summary['total_files']}\n"
            f"Imported: {summary['imported']}\n"
            f"Skipped (already exist): {summary['skipped']}\n"
            f"Errors: {summary['errors']}\n\n"
            f"Total entries linked: {summary['total_entries_linked']}\n"
            f"Total unmatched bullets: {summary['total_entries_unmatched']}",
            title="Import Summary",
        ))

        if summary['unmatched_bullets']:
            console.print(f"\n[yellow]{len(summary['unmatched_bullets'])} unmatched bullets flagged as suggestions.[/yellow]")
            console.print("View with: [cyan]jj corpus suggestions[/cyan]")


@resume_app.command("validate")
def resume_validate(
    resume_id: int = typer.Argument(..., help="Resume ID to validate"),
):
    """Validate a resume against current corpus.

    Re-checks all bullets to ensure they still exist in the corpus.

    Examples:
        jj resume validate 1
    """
    if not JJ_HOME.exists():
        console.print("[red]Job Journal not initialized. Run 'jj init' first.[/red]")
        raise typer.Exit(1)

    from jj.resume_gen import revalidate_resume

    console.print(f"[bold]Validating resume {resume_id}...[/bold]\n")

    result = revalidate_resume(resume_id)

    if result["is_valid"]:
        console.print(Panel.fit(
            f"[green]Resume is valid![/green]\n\n"
            f"Total bullets: {result['total_bullets']}\n"
            f"Drift score: {result['drift_score']}",
            title="Validation Passed",
        ))
    else:
        console.print(Panel.fit(
            f"[red]Resume has invalid bullets![/red]\n\n"
            f"Total bullets: {result['total_bullets']}\n"
            f"Invalid bullets: {len(result['invalid_bullets'])}\n"
            f"Drift score: {result['drift_score']}",
            title="Validation Failed",
        ))

        console.print("\n[red]Invalid bullets:[/red]")
        for item in result["invalid_bullets"]:
            console.print(f"  - {item['bullet'][:80]}...")
            if item.get("closest_match"):
                console.print(f"    [dim]Closest match ({item['score']:.0%}): {item['closest_match']['text'][:60]}...[/dim]")


@resume_app.command("entries")
def resume_entries(
    resume_id: int = typer.Argument(..., help="Resume ID"),
):
    """Show which corpus entries were used in a resume.

    Useful for understanding what content appears in each resume.

    Examples:
        jj resume entries 1
    """
    if not JJ_HOME.exists():
        console.print("[red]Job Journal not initialized. Run 'jj init' first.[/red]")
        raise typer.Exit(1)

    from jj.db import get_resume_entries, get_resume

    resume = get_resume(resume_id)
    if not resume:
        console.print(f"[red]Resume {resume_id} not found.[/red]")
        raise typer.Exit(1)

    entries = get_resume_entries(resume_id)

    if not entries:
        console.print(f"[yellow]No entries linked to resume {resume_id}.[/yellow]")
        return

    console.print(f"[bold]{resume['filename']}[/bold]")
    console.print(f"[dim]{len(entries)} entries used[/dim]\n")

    from rich.table import Table

    table = Table()
    table.add_column("Pos", style="dim", width=4)
    table.add_column("Role", width=25)
    table.add_column("Entry", width=70)

    for entry in entries:
        role_str = f"{entry.get('role_title', '')} @ {entry.get('role_company', '')}"
        if len(role_str) > 25:
            role_str = role_str[:22] + "..."

        text = entry["text"]
        if len(text) > 70:
            text = text[:67] + "..."

        table.add_row(
            str(entry.get("position", "-")),
            role_str,
            text,
        )

    console.print(table)


@app.command()
def stats():
    """Show corpus statistics."""

    if not JJ_HOME.exists():
        console.print("[red]Job Journal not initialized. Run 'jj init' first.[/red]")
        raise typer.Exit(1)

    s = get_stats()

    console.print(Panel.fit(
        f"[bold]Corpus Statistics[/bold]\n\n"
        f"Roles: {s['roles']}\n"
        f"Entries: {s['entries']}\n"
        f"Skills: {s['skills']}\n"
        f"Resumes: {s['resumes']}\n"
        f"Applications: {s['applications']}",
        title="Job Journal Stats",
    ))


@app.command()
def serve(
    port: int = typer.Option(8000, "--port", "-p", help="Port to run on"),
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Host to bind to"),
    reload: bool = typer.Option(False, "--reload", "-r", help="Enable auto-reload for development"),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open browser automatically"),
):
    """Start the Job Journal web dashboard."""

    if not JJ_HOME.exists():
        console.print("[red]Job Journal not initialized. Run 'jj init' first.[/red]")
        raise typer.Exit(1)

    try:
        import uvicorn
    except ImportError:
        console.print("[red]Web dependencies not installed.[/red]")
        console.print("Install with: [cyan]pip install job-journal[web][/cyan]")
        raise typer.Exit(1)

    console.print(Panel.fit(
        f"[bold green]Job Journal Dashboard[/bold green]\n\n"
        f"Starting web server at [cyan]http://{host}:{port}[/cyan]\n\n"
        f"[dim]AI workflows still run in terminal:[/dim]\n"
        f"  /jobs     - Search for jobs\n"
        f"  /apply    - Apply to jobs\n"
        f"  /interview - Build your corpus",
        title="Web Dashboard",
    ))

    # Open browser
    if open_browser:
        import webbrowser
        import threading

        def open_browser_delayed():
            import time
            time.sleep(1)  # Wait for server to start
            webbrowser.open(f"http://{host}:{port}")

        threading.Thread(target=open_browser_delayed, daemon=True).start()

    # Run the server
    uvicorn.run(
        "jj.web.app:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


# =============================================================================
# Greenhouse Commands
# =============================================================================

greenhouse_app = typer.Typer(
    name="greenhouse",
    help="Poll my.greenhouse.io for job listings.",
    no_args_is_help=True,
)
app.add_typer(greenhouse_app, name="greenhouse")


@greenhouse_app.command("setup")
def greenhouse_setup(
    har: Path = typer.Option(..., "--har", "-h", help="Path to HAR file exported from browser"),
):
    """Import authentication from a HAR file.

    Export a HAR file from browser DevTools after searching on my.greenhouse.io,
    then run this command to extract and save the authentication credentials.

    Example:
        jj greenhouse setup --har ~/Downloads/my.greenhouse.io.har
    """
    if not JJ_HOME.exists():
        console.print("[red]Job Journal not initialized. Run 'jj init' first.[/red]")
        raise typer.Exit(1)

    from jj.greenhouse import extract_auth_from_har, save_auth

    try:
        auth = extract_auth_from_har(har)
        save_auth(auth)

        console.print(Panel.fit(
            f"[green]Authentication saved![/green]\n\n"
            f"CSRF Token: {auth.csrf_token[:20]}...\n"
            f"Inertia Version: {auth.inertia_version}\n"
            f"Cookies: {len(auth.cookies)} session cookies",
            title="Greenhouse Setup",
        ))

        console.print("\nNext steps:")
        console.print("  [cyan]jj greenhouse poll[/cyan]           - Search for jobs")
        console.print("  [cyan]jj greenhouse config --show[/cyan]  - View search defaults")

    except FileNotFoundError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)
    except ValueError as e:
        console.print(f"[red]Error parsing HAR: {e}[/red]")
        raise typer.Exit(1)


@greenhouse_app.command("poll")
def greenhouse_poll(
    query: Optional[str] = typer.Option(None, "--query", "-q", help="Job title or keyword search"),
    location: Optional[str] = typer.Option(None, "--location", "-l", help="Location (e.g., 'Austin, Texas')"),
    date_posted: Optional[str] = typer.Option(None, "--date", "-d", help="Date filter: past_day, past_week, past_month"),
    import_jobs: bool = typer.Option(False, "--import", "-i", help="Import jobs as prospects"),
    max_pages: int = typer.Option(3, "--pages", "-p", help="Maximum pages to fetch"),
):
    """Search Greenhouse for job listings.

    Uses saved authentication and search defaults from config.

    Examples:
        jj greenhouse poll
        jj greenhouse poll --query "Product Manager" --date past_day
        jj greenhouse poll --import
    """
    if not JJ_HOME.exists():
        console.print("[red]Job Journal not initialized. Run 'jj init' first.[/red]")
        raise typer.Exit(1)

    from jj.greenhouse import (
        load_auth,
        GreenhouseClient,
        get_search_config,
        import_jobs_as_prospects,
    )

    # Load authentication
    auth = load_auth()
    if not auth:
        console.print("[red]Greenhouse not configured. Run 'jj greenhouse setup --har <file>' first.[/red]")
        raise typer.Exit(1)

    # Get search config defaults
    config = get_search_config()

    # Use provided args or fall back to config
    search_query = query or config.get("query")
    search_location = location or config.get("location")
    search_date = date_posted or config.get("date_posted")
    search_lat = config.get("lat")
    search_lon = config.get("lon")

    console.print("[bold]Searching Greenhouse...[/bold]\n")

    if search_query:
        console.print(f"Query: {search_query}")
    if search_location:
        console.print(f"Location: {search_location}")
    if search_date:
        console.print(f"Date: {search_date}")
    console.print()

    # Search for jobs
    client = GreenhouseClient(auth)

    try:
        jobs = client.search_all_pages(
            query=search_query,
            location=search_location,
            lat=search_lat,
            lon=search_lon,
            date_posted=search_date,
            max_pages=max_pages,
        )
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error fetching jobs: {e}[/red]")
        raise typer.Exit(1)

    if not jobs:
        console.print("[yellow]No jobs found matching your search.[/yellow]")
        return

    # Display results in a table
    from rich.table import Table

    table = Table(title=f"Found {len(jobs)} Jobs")
    table.add_column("#", style="dim", width=3)
    table.add_column("Company", width=20)
    table.add_column("Position", width=30)
    table.add_column("Location", width=20)

    for i, job in enumerate(jobs, 1):
        row = [
            str(i),
            job.company_name[:20] if len(job.company_name) > 20 else job.company_name,
            job.title[:30] if len(job.title) > 30 else job.title,
            job.location[:20] if len(job.location) > 20 else job.location,
        ]
        table.add_row(*row)

    console.print(table)

    # Import if requested
    if import_jobs:
        console.print("\n[bold]Importing as prospects...[/bold]")
        result = import_jobs_as_prospects(jobs)
        console.print(f"  Imported: {result['imported']}")
        console.print(f"  Skipped (already exist): {result['skipped']}")

        if result['imported'] > 0:
            console.print("\n[green]Jobs imported! View with:[/green]")
            console.print("  [cyan]jj stats[/cyan]")


@greenhouse_app.command("config")
def greenhouse_config(
    show: bool = typer.Option(False, "--show", "-s", help="Show current configuration"),
    query: Optional[str] = typer.Option(None, "--query", "-q", help="Set default search query"),
    location: Optional[str] = typer.Option(None, "--location", "-l", help="Set default location"),
    lat: Optional[float] = typer.Option(None, "--lat", help="Set latitude for location"),
    lon: Optional[float] = typer.Option(None, "--lon", help="Set longitude for location"),
    date_posted: Optional[str] = typer.Option(None, "--date", "-d", help="Set default date filter"),
):
    """View or set Greenhouse search defaults.

    Examples:
        jj greenhouse config --show
        jj greenhouse config --query "Product Manager" --location "Austin, Texas"
        jj greenhouse config --date past_day
    """
    if not JJ_HOME.exists():
        console.print("[red]Job Journal not initialized. Run 'jj init' first.[/red]")
        raise typer.Exit(1)

    from jj.greenhouse import get_search_config, save_search_config, load_auth

    if show or (query is None and location is None and lat is None and lon is None and date_posted is None):
        # Show current config
        config = get_search_config()
        auth = load_auth()

        console.print(Panel.fit(
            f"[bold]Search Defaults[/bold]\n\n"
            f"Query: {config.get('query', '[dim]not set[/dim]')}\n"
            f"Location: {config.get('location', '[dim]not set[/dim]')}\n"
            f"Latitude: {config.get('lat', '[dim]not set[/dim]')}\n"
            f"Longitude: {config.get('lon', '[dim]not set[/dim]')}\n"
            f"Date Filter: {config.get('date_posted', '[dim]not set[/dim]')}\n\n"
            f"[bold]Authentication[/bold]\n"
            f"Configured: {'[green]Yes[/green]' if auth else '[red]No[/red]'}",
            title="Greenhouse Config",
        ))

        if not config:
            console.print("\n[dim]Set defaults with:[/dim]")
            console.print("  jj greenhouse config --query 'Product Manager' --location 'Austin, Texas'")

        return

    # Update config
    save_search_config(
        query=query,
        location=location,
        lat=lat,
        lon=lon,
        date_posted=date_posted,
    )

    console.print("[green]Configuration updated![/green]")

    # Show what was updated
    updates = []
    if query:
        updates.append(f"Query: {query}")
    if location:
        updates.append(f"Location: {location}")
    if lat:
        updates.append(f"Latitude: {lat}")
    if lon:
        updates.append(f"Longitude: {lon}")
    if date_posted:
        updates.append(f"Date Filter: {date_posted}")

    for update in updates:
        console.print(f"  {update}")


# =============================================================================
# Email Commands
# =============================================================================

email_app = typer.Typer(
    name="email",
    help="Gmail integration for job application verification.",
    no_args_is_help=True,
)
app.add_typer(email_app, name="email")


@email_app.command("setup")
def email_setup():
    """Set up Gmail API authentication.

    Requires credentials.json from Google Cloud Console in ~/.job-journal/.
    Will open a browser to authorize access on first run.
    """
    if not JJ_HOME.exists():
        console.print("[red]Job Journal not initialized. Run 'jj init' first.[/red]")
        raise typer.Exit(1)

    try:
        from jj.gmail_checker import GmailClient, CREDENTIALS_PATH, TOKEN_PATH
    except ImportError as e:
        console.print("[red]Gmail dependencies not installed.[/red]")
        console.print("Install with: [cyan]pip install google-api-python-client google-auth-oauthlib[/cyan]")
        raise typer.Exit(1)

    if not CREDENTIALS_PATH.exists():
        console.print(f"[red]credentials.json not found at {CREDENTIALS_PATH}[/red]")
        console.print("\nTo set up Gmail integration:")
        console.print("1. Go to https://console.cloud.google.com/apis/credentials")
        console.print("2. Create OAuth 2.0 Client ID credentials")
        console.print("3. Download as credentials.json")
        console.print(f"4. Copy to {JJ_HOME}/")
        raise typer.Exit(1)

    console.print("[bold]Authenticating with Gmail...[/bold]")
    console.print("A browser window will open for authorization.\n")

    try:
        client = GmailClient()
        client.authenticate()

        console.print(Panel.fit(
            f"[green]Gmail authentication successful![/green]\n\n"
            f"Token saved to: {TOKEN_PATH}\n\n"
            "Next steps:\n"
            "  [cyan]jj email verify[/cyan]   - Check for missing confirmations\n"
            "  [cyan]jj email updates[/cyan]  - Search for new updates",
            title="Gmail Setup",
        ))
    except Exception as e:
        console.print(f"[red]Authentication failed: {e}[/red]")
        raise typer.Exit(1)


@email_app.command("verify")
def email_verify(
    status: str = typer.Option("applied", "--status", "-s", help="Filter applications by status"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed output"),
):
    """Check for missing confirmation emails.

    Searches Gmail for confirmation emails for each application and reports
    which ones are missing.

    Examples:
        jj email verify
        jj email verify --status applied
        jj email verify --verbose
    """
    if not JJ_HOME.exists():
        console.print("[red]Job Journal not initialized. Run 'jj init' first.[/red]")
        raise typer.Exit(1)

    try:
        from jj.gmail_checker import verify_confirmations
    except ImportError as e:
        console.print("[red]Gmail dependencies not installed.[/red]")
        console.print("Install with: [cyan]pip install google-api-python-client google-auth-oauthlib[/cyan]")
        raise typer.Exit(1)

    from jj.db import get_applications

    # Get applications
    applications = get_applications(status=status)

    if not applications:
        console.print(f"[yellow]No applications with status '{status}' found.[/yellow]")
        return

    console.print(f"[bold]Checking {len(applications)} {status} applications...[/bold]\n")

    try:
        results = verify_confirmations(applications, verbose=verbose)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        console.print("\nRun [cyan]jj email setup[/cyan] first.")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)

    # Display results
    confirmed = [r for r in results if r.confirmed]
    missing = [r for r in results if not r.confirmed]

    for result in results:
        if result.confirmed:
            date_str = result.email.date.strftime("%Y-%m-%d") if result.email else ""
            console.print(f"[green]\u2713[/green] {result.company} - Confirmed ({date_str})")
            if verbose and result.email:
                console.print(f"    [dim]{result.email.subject}[/dim]")
        else:
            console.print(f"[red]\u2717[/red] {result.company} - NO CONFIRMATION FOUND")

    console.print()
    console.print(f"[bold]Summary:[/bold]")
    console.print(f"  Confirmed: {len(confirmed)}")
    console.print(f"  Missing: {len(missing)}")

    if missing:
        console.print("\n[yellow]Missing confirmations:[/yellow]")
        for result in missing:
            applied_str = ""
            if result.applied_at:
                applied_str = f" (applied {result.applied_at.strftime('%Y-%m-%d')})"
            console.print(f"  - {result.company}{applied_str}")


@email_app.command("updates")
def email_updates(
    days: int = typer.Option(7, "--days", "-d", help="Search emails from last N days"),
    status: str = typer.Option("applied", "--status", "-s", help="Filter applications by status"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed output"),
):
    """Search for new update emails (interviews, rejections, next steps).

    Examples:
        jj email updates
        jj email updates --days 14
        jj email updates --status screening
    """
    if not JJ_HOME.exists():
        console.print("[red]Job Journal not initialized. Run 'jj init' first.[/red]")
        raise typer.Exit(1)

    try:
        from jj.gmail_checker import search_updates
    except ImportError as e:
        console.print("[red]Gmail dependencies not installed.[/red]")
        console.print("Install with: [cyan]pip install google-api-python-client google-auth-oauthlib[/cyan]")
        raise typer.Exit(1)

    from datetime import datetime, timedelta
    from jj.db import get_applications

    # Get applications
    applications = get_applications(status=status)

    if not applications:
        console.print(f"[yellow]No applications with status '{status}' found.[/yellow]")
        return

    since = datetime.now() - timedelta(days=days)
    console.print(f"[bold]Searching for updates since {since.strftime('%Y-%m-%d')}...[/bold]\n")

    try:
        results = search_updates(applications, since=since, verbose=verbose)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        console.print("\nRun [cyan]jj email setup[/cyan] first.")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)

    if not results:
        console.print("[green]No new updates found.[/green]")
        return

    # Group by type
    from collections import defaultdict
    by_type = defaultdict(list)
    for r in results:
        by_type[r.update_type].append(r)

    # Display results
    type_labels = {
        "interview": ("[green]INTERVIEW[/green]", "Schedule interview"),
        "next_steps": ("[cyan]ACTION[/cyan]", "Action required"),
        "rejection": ("[red]REJECTION[/red]", "Application closed"),
        "update": ("[yellow]UPDATE[/yellow]", "Check email"),
        "unknown": ("[dim]UPDATE[/dim]", "Check email"),
    }

    console.print(f"[bold]Found {len(results)} updates:[/bold]\n")

    for result in results:
        label, action = type_labels.get(result.update_type, ("[dim]UPDATE[/dim]", "Check email"))

        console.print(f"{label}: {result.company} - \"{result.email.subject}\"")

        if result.action_required:
            console.print(f"     [bold]Action required:[/bold] {action}")
        else:
            console.print(f"     Status change? {action}")

        console.print(f"     Link: [link={result.email.gmail_link}]{result.email.gmail_link}[/link]")
        console.print()


@email_app.command("sync")
def email_sync(
    days: int = typer.Option(7, "--days", "-d", help="Search emails from last N days"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed output"),
):
    """Run both verify and updates (full sync).

    Examples:
        jj email sync
        jj email sync --days 14
    """
    if not JJ_HOME.exists():
        console.print("[red]Job Journal not initialized. Run 'jj init' first.[/red]")
        raise typer.Exit(1)

    console.print(Panel.fit(
        "[bold]Gmail Sync[/bold]\n\n"
        "Running verification and update checks...",
        title="Email Sync",
    ))

    console.print("\n[bold cyan]Step 1: Verifying confirmations[/bold cyan]\n")

    # Run verify
    from typer.testing import CliRunner
    runner = CliRunner()

    # Instead of invoking CLI, just call the functions directly
    try:
        from jj.gmail_checker import verify_confirmations, search_updates
        from jj.db import get_applications
        from datetime import datetime, timedelta
    except ImportError as e:
        console.print("[red]Gmail dependencies not installed.[/red]")
        console.print("Install with: [cyan]pip install google-api-python-client google-auth-oauthlib[/cyan]")
        raise typer.Exit(1)

    # Verify confirmations
    applications = get_applications(status="applied")

    if applications:
        console.print(f"Checking {len(applications)} applied applications...\n")

        try:
            verify_results = verify_confirmations(applications, verbose=verbose)

            confirmed = [r for r in verify_results if r.confirmed]
            missing = [r for r in verify_results if not r.confirmed]

            for result in verify_results:
                if result.confirmed:
                    date_str = result.email.date.strftime("%Y-%m-%d") if result.email else ""
                    console.print(f"[green]\u2713[/green] {result.company} ({date_str})")
                else:
                    console.print(f"[red]\u2717[/red] {result.company} - MISSING")

            console.print(f"\nConfirmed: {len(confirmed)}, Missing: {len(missing)}")

        except Exception as e:
            console.print(f"[red]Verification error: {e}[/red]")
    else:
        console.print("[dim]No applied applications to verify.[/dim]")

    console.print("\n[bold cyan]Step 2: Searching for updates[/bold cyan]\n")

    # Search updates
    all_applications = get_applications()

    if all_applications:
        since = datetime.now() - timedelta(days=days)
        console.print(f"Searching updates since {since.strftime('%Y-%m-%d')}...\n")

        try:
            update_results = search_updates(all_applications, since=since, verbose=verbose)

            if update_results:
                console.print(f"[bold]Found {len(update_results)} updates:[/bold]\n")

                for result in update_results:
                    type_emoji = {
                        "interview": "[green]INTERVIEW[/green]",
                        "next_steps": "[cyan]ACTION[/cyan]",
                        "rejection": "[red]REJECTION[/red]",
                    }.get(result.update_type, "[yellow]UPDATE[/yellow]")

                    console.print(f"{type_emoji}: {result.company}")
                    console.print(f"    {result.email.subject}")
                    console.print(f"    [link={result.email.gmail_link}]Open in Gmail[/link]")
                    console.print()
            else:
                console.print("[green]No new updates found.[/green]")

        except Exception as e:
            console.print(f"[red]Update search error: {e}[/red]")
    else:
        console.print("[dim]No applications to search updates for.[/dim]")

    console.print("\n[bold green]Sync complete![/bold green]")


@email_app.command("learn")
def email_learn(
    company: str = typer.Argument(..., help="Company name to learn domain for"),
):
    """Learn a company's email domain from recent emails.

    Searches for recent emails from the company and saves the sender domain
    for future searches.

    Example:
        jj email learn "Vercel"
    """
    if not JJ_HOME.exists():
        console.print("[red]Job Journal not initialized. Run 'jj init' first.[/red]")
        raise typer.Exit(1)

    try:
        from jj.gmail_checker import (
            search_company_emails, save_company_domain, get_company_domain
        )
        import re
    except ImportError as e:
        console.print("[red]Gmail dependencies not installed.[/red]")
        console.print("Install with: [cyan]pip install google-api-python-client google-auth-oauthlib[/cyan]")
        raise typer.Exit(1)

    # Check existing
    existing = get_company_domain(company)
    if existing:
        console.print(f"[yellow]{company} already has domain: {existing}[/yellow]")
        if not Confirm.ask("Search for a different domain?"):
            return

    console.print(f"[bold]Searching for emails from {company}...[/bold]\n")

    try:
        emails = search_company_emails(company, max_results=10)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        console.print("\nRun [cyan]jj email setup[/cyan] first.")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)

    if not emails:
        console.print(f"[yellow]No emails found for {company}.[/yellow]")
        return

    # Extract unique domains
    domains = {}
    for email in emails:
        match = re.search(r"@([a-zA-Z0-9.-]+)", email.sender)
        if match:
            domain = match.group(1).lower()
            # Skip common ATS domains
            if any(ats in domain for ats in ["ashby", "greenhouse", "lever", "icims", "rippling", "workday"]):
                continue
            if domain not in domains:
                domains[domain] = []
            domains[domain].append(email)

    if not domains:
        console.print(f"[yellow]Only found ATS emails, no company domain detected.[/yellow]")
        return

    console.print(f"Found {len(emails)} emails. Detected domains:\n")

    # Show options
    domain_list = list(domains.keys())
    for i, domain in enumerate(domain_list, 1):
        count = len(domains[domain])
        sample = domains[domain][0].subject[:50]
        console.print(f"  {i}. {domain} ({count} emails)")
        console.print(f"     [dim]Example: {sample}...[/dim]")

    console.print()

    # Let user select
    if len(domain_list) == 1:
        selected_domain = domain_list[0]
        if Confirm.ask(f"Save {selected_domain} as {company}'s domain?"):
            save_company_domain(company, selected_domain)
            console.print(f"[green]Saved: {company} -> {selected_domain}[/green]")
    else:
        choice = Prompt.ask(
            "Select domain number to save",
            choices=[str(i) for i in range(1, len(domain_list) + 1)],
            default="1"
        )
        selected_domain = domain_list[int(choice) - 1]
        save_company_domain(company, selected_domain)
        console.print(f"[green]Saved: {company} -> {selected_domain}[/green]")


@email_app.command("test")
def email_test(
    company: str = typer.Argument(..., help="Company name to search"),
    max_results: int = typer.Option(5, "--max", "-m", help="Maximum results to show"),
):
    """Test email search for a specific company.

    Useful for debugging search queries and seeing what emails match.

    Example:
        jj email test "Vercel"
    """
    if not JJ_HOME.exists():
        console.print("[red]Job Journal not initialized. Run 'jj init' first.[/red]")
        raise typer.Exit(1)

    try:
        from jj.gmail_checker import search_company_emails
    except ImportError as e:
        console.print("[red]Gmail dependencies not installed.[/red]")
        console.print("Install with: [cyan]pip install google-api-python-client google-auth-oauthlib[/cyan]")
        raise typer.Exit(1)

    console.print(f"[bold]Searching for emails related to: {company}[/bold]\n")

    try:
        emails = search_company_emails(company, max_results=max_results)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        console.print("\nRun [cyan]jj email setup[/cyan] first.")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)

    if not emails:
        console.print(f"[yellow]No emails found for {company}.[/yellow]")
        return

    console.print(f"Found {len(emails)} emails:\n")

    for email in emails:
        type_color = {
            "confirmation": "green",
            "interview": "cyan",
            "rejection": "red",
            "next_steps": "yellow",
        }.get(email.match_type, "white")

        console.print(f"[{type_color}][{email.match_type.upper()}][/{type_color}]")
        console.print(f"  From: {email.sender}")
        console.print(f"  Subject: {email.subject}")
        console.print(f"  Date: {email.date.strftime('%Y-%m-%d %H:%M')}")
        console.print(f"  Link: [link={email.gmail_link}]{email.gmail_link}[/link]")
        console.print()


# --------------------------------------------------------------------------
# Worker subcommands
# --------------------------------------------------------------------------

worker_app = typer.Typer(
    help="Background task worker for automated email sync and job monitoring.",
)
app.add_typer(worker_app, name="worker")


@worker_app.command("start")
def worker_start(
    poll_interval: int = typer.Option(5, "--interval", "-i", help="Seconds between task checks"),
    daemon: bool = typer.Option(False, "--daemon", "-d", help="Run in background as daemon"),
):
    """Start the background worker."""
    from jj.worker import start_worker
    start_worker(poll_interval=poll_interval, daemon=daemon)


@worker_app.command("stop")
def worker_stop():
    """Stop the background worker."""
    from jj.worker import stop_worker
    stop_worker()


@worker_app.command("status")
def worker_status_cmd():
    """Show worker status and recent tasks."""
    from jj.worker import worker_status
    worker_status()


@worker_app.command("sync")
def worker_sync(
    recurring: bool = typer.Option(False, "--recurring", "-r", help="Schedule recurring sync"),
    hours: int = typer.Option(1, "--hours", help="Hours between syncs (with --recurring)"),
):
    """Trigger email sync immediately."""
    from jj.worker import run_task_now, schedule_email_sync

    if recurring:
        schedule_email_sync(hours=hours)
    else:
        run_task_now('email_sync')


@worker_app.command("run")
def worker_run_task(
    task_type: str = typer.Argument(..., help="Task type to run"),
    payload: Optional[str] = typer.Option(None, "--payload", "-p", help="JSON payload"),
):
    """Run a specific task immediately (for testing)."""
    import json
    from jj.worker import run_task_now

    payload_dict = json.loads(payload) if payload else None
    run_task_now(task_type, payload=payload_dict)


if __name__ == "__main__":
    app()
