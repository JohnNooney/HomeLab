"""Rich console helpers and common utilities."""

from __future__ import annotations

import shutil
import subprocess
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table
from rich.text import Text

console = Console()


def header(title: str, subtitle: str = "") -> None:
    """Display a styled header panel."""
    content = Text(title, style="bold cyan")
    if subtitle:
        content.append(f"\n{subtitle}", style="dim")
    console.print(Panel(content, border_style="cyan", padding=(1, 2)))


def phase_header(phase: str, description: str) -> None:
    """Display a phase header."""
    console.print()
    console.rule(f"[bold cyan]{phase}[/bold cyan]", style="cyan")
    console.print(f"  [dim]{description}[/dim]")
    console.print()


def step(number: int, description: str) -> None:
    """Display a step indicator."""
    console.print(f"  [bold yellow]Step {number}:[/bold yellow] {description}")


def success(message: str) -> None:
    """Display a success message."""
    console.print(f"  [bold green]\u2714[/bold green] {message}")


def error(message: str) -> None:
    """Display an error message."""
    console.print(f"  [bold red]\u2718[/bold red] {message}")


def warn(message: str) -> None:
    """Display a warning message."""
    console.print(f"  [bold yellow]\u26a0[/bold yellow] {message}")


def info(message: str) -> None:
    """Display an info message."""
    console.print(f"  [bold blue]\u2139[/bold blue] {message}")


def prompt_text(message: str, default: str = "") -> str:
    """Prompt user for text input."""
    return Prompt.ask(f"  {message}", default=default or None) or default


def prompt_int(message: str, default: int = 0, min_val: int = 0, max_val: int = 100) -> int:
    """Prompt user for integer input."""
    while True:
        val = IntPrompt.ask(f"  {message}", default=default)
        if min_val <= val <= max_val:
            return val
        error(f"Value must be between {min_val} and {max_val}")


def prompt_confirm(message: str, default: bool = True) -> bool:
    """Prompt user for yes/no confirmation."""
    return Confirm.ask(f"  {message}", default=default)


def prompt_choice(message: str, choices: list[str], default: str = "") -> str:
    """Prompt user to pick from a list of choices."""
    console.print(f"  {message}")
    for i, choice in enumerate(choices, 1):
        console.print(f"    [cyan]{i}[/cyan]. {choice}")
    while True:
        val = IntPrompt.ask("  Select", default=choices.index(default) + 1 if default in choices else 1)
        if 1 <= val <= len(choices):
            return choices[val - 1]
        error(f"Pick 1-{len(choices)}")


def display_config_table(title: str, data: dict) -> None:
    """Display a key-value config table."""
    table = Table(title=title, show_header=False, border_style="dim")
    table.add_column("Key", style="bold")
    table.add_column("Value", style="green")
    for k, v in data.items():
        table.add_row(str(k), str(v))
    console.print(table)


def display_preflight_table(phase_name: str, results: list[tuple[str, bool]]) -> None:
    """Display a pre-flight check results table."""
    table = Table(title=f"Pre-flight: {phase_name}", border_style="dim")
    table.add_column("Check", style="bold")
    table.add_column("Status", justify="center")
    for label, passed in results:
        icon = "[bold green]\u2714[/bold green]" if passed else "[bold red]\u2718[/bold red]"
        table.add_row(label, icon)
    console.print(table)


def display_vm_table(vms: list[dict]) -> None:
    """Display a table of VMs."""
    table = Table(title="Kubernetes VMs", border_style="cyan")
    table.add_column("ID", style="bold")
    table.add_column("Name", style="cyan")
    table.add_column("IP Address", style="green")
    table.add_column("Role", style="yellow")
    table.add_column("CPU", justify="right")
    table.add_column("RAM", justify="right")
    for vm in vms:
        table.add_row(
            str(vm["id"]),
            vm["name"],
            vm["ip"],
            vm["role"],
            str(vm["cores"]),
            f"{vm['memory']}MB",
        )
    console.print(table)


def run_local(
    command: str,
    cwd: Optional[str] = None,
    check: bool = True,
    stream: bool = False,
) -> tuple[int, str, str]:
    """Run a command on the local machine.

    Returns:
        Tuple of (exit_code, stdout, stderr).
    """
    if stream:
        proc = subprocess.Popen(
            command,
            shell=True,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout_lines = []
        stderr_lines = []
        for line in iter(proc.stdout.readline, ""):
            console.print(f"  {line}", end="", highlight=False)
            stdout_lines.append(line)
        proc.wait()
        stderr_out = proc.stderr.read()
        if stderr_out:
            stderr_lines.append(stderr_out)
        stdout = "".join(stdout_lines)
        stderr = "".join(stderr_lines)
        rc = proc.returncode
    else:
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
        )
        rc = result.returncode
        stdout = result.stdout
        stderr = result.stderr

    if check and rc != 0:
        raise RuntimeError(f"Local command failed (exit {rc}): {command}\n{stderr.strip()}")

    return rc, stdout, stderr


def check_local_tool(name: str) -> bool:
    """Check if a tool is available in PATH."""
    return shutil.which(name) is not None
