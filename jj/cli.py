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


@app.command()
def corpus(
    edit: bool = typer.Option(False, "--edit", "-e", help="Open corpus in editor"),
):
    """View or edit your corpus."""

    if not JJ_HOME.exists():
        console.print("[red]Job Journal not initialized. Run 'jj init' first.[/red]")
        raise typer.Exit(1)

    corpus_path = JJ_HOME / "corpus.md"

    if edit:
        import os
        editor = os.environ.get("EDITOR", "vim")
        os.system(f'{editor} "{corpus_path}"')
    else:
        if corpus_path.exists():
            console.print(corpus_path.read_text())
        else:
            console.print("[yellow]No corpus yet. Run 'jj interview' to build one.[/yellow]")


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


if __name__ == "__main__":
    app()
