"""Shared Rich console for structured, coloured terminal output."""

import sys

from rich.console import Console

console = Console(highlight=False)
_err = Console(stderr=True, highlight=False)


def info(msg: str) -> None:
    console.print(f"[bold blue]INFO[/]     {msg}")


def debug(msg: str) -> None:
    console.print(f"[dim]DEBUG[/]    {msg}", style="dim")


def warning(msg: str) -> None:
    _err.print(f"[bold yellow]WARNING[/]  {msg}")


def error(msg: str) -> None:
    _err.print(f"[bold red]ERROR[/]    {msg}")


def status(msg: str) -> None:
    """General progress / status message (no prefix)."""
    console.print(msg)


def section(title: str) -> None:
    """Print a section header rule."""
    console.rule(f"[bold]{title}[/]")


def success(msg: str) -> None:
    console.print(f"[bold green]OK[/]       {msg}")


def detail(msg: str) -> None:
    """Indented detail line (no prefix)."""
    console.print(f"         {msg}")


def fatal(msg: str) -> None:
    """Print error and exit."""
    error(msg)
    sys.exit(1)
