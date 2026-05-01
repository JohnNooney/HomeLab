"""HomeLab Setup CLI — main entry point and menu orchestration."""

from __future__ import annotations

import os
import sys

import click
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from homelab_setup import __version__
from homelab_setup.config import gather_config, load_config, save_config
from homelab_setup.phases.phase3 import run_phase3
from homelab_setup.phases.phase4_k3s import run_phase4_k3s
from homelab_setup.phases.phase4_kubeadm import run_phase4_kubeadm
from homelab_setup.phases.phase5 import run_phase5
from homelab_setup.phases.phase_teardown import run_teardown
from homelab_setup.troubleshoot import run_troubleshoot
from homelab_setup.utils import (
    check_local_tool,
    console,
    error,
    header,
    info,
    prompt_confirm,
    run_local,
    success,
    warn,
)

BANNER = r"""
 _   _                      _          _
| | | | ___  _ __ ___   ___| |    __ _| |__
| |_| |/ _ \| '_ ` _ \ / _ \ |   / _` | '_ \
|  _  | (_) | | | | | |  __/ |__| (_| | |_) |
|_| |_|\___/|_| |_| |_|\___|_____\__,_|_.__/
"""


def _find_project_root() -> str:
    """Walk up from this file to find the project root (contains setup-cli/)."""
    # This file is at setup-cli/homelab_setup/cli.py
    here = os.path.dirname(os.path.abspath(__file__))
    setup_cli_dir = os.path.dirname(here)
    project_root = os.path.dirname(setup_cli_dir)
    return project_root


def _run_phase4(config: dict, project_root: str, force: bool = False) -> bool:
    """Dispatch to k3s or kubeadm based on cluster mode."""
    mode = config["cluster"]["mode"]
    if mode == "k3s":
        return run_phase4_k3s(config, force=force)
    else:
        return run_phase4_kubeadm(config, project_root, force=force)


def _run_status_check(config: dict) -> None:
    """Quick status check of current cluster state."""
    console.rule("[bold cyan]Status Check[/bold cyan]", style="cyan")

    mode = config["cluster"]["mode"]
    cp_ip = config["cluster"]["control_plane_ip"]
    info(f"Mode: {mode}")
    info(f"Control plane: {cp_ip}")

    if not check_local_tool("kubectl"):
        warn("kubectl not found — cannot check cluster status")
        return

    rc, stdout, _ = run_local("kubectl get nodes", check=False)
    if rc == 0:
        success("Cluster reachable")
        for line in stdout.strip().splitlines():
            info(f"  {line}")
    else:
        warn("Cluster not reachable (kubectl get nodes failed)")

    rc, stdout, _ = run_local("kubectl get pods --all-namespaces --field-selector=status.phase!=Running,status.phase!=Succeeded 2>/dev/null", check=False)
    if rc == 0 and stdout.strip():
        warn("Non-running pods:")
        for line in stdout.strip().splitlines():
            info(f"  {line}")
    else:
        success("All pods healthy")


def _interactive_menu(project_root: str) -> None:
    """Main interactive menu loop."""
    console.print(BANNER, style="cyan")
    header("HomeLab Setup CLI", f"v{__version__} — Interactive Proxmox + K8s Bootstrap")

    # Load or gather config
    config = load_config(project_root)
    if not config["proxmox"]["host"]:
        info("No configuration found. Let's set things up.")
        config = gather_config(project_root)
    else:
        info(f"Loaded config: {config['cluster']['mode']} mode, "
             f"control plane {config['cluster']['control_plane_ip']}, "
             f"{config['cluster']['worker_count']} workers")
        if prompt_confirm("Reconfigure settings?", default=False):
            config = gather_config(project_root)

    while True:
        console.print()
        console.print("[bold]Main Menu[/bold]")
        console.print("  [cyan]1[/cyan]. Phase 3: Provision K8s VMs on Proxmox")
        console.print("  [cyan]2[/cyan]. Phase 4: Install Kubernetes")
        console.print("  [cyan]3[/cyan]. Phase 5: Bootstrap Cluster Services")
        console.print("  [cyan]4[/cyan]. Run All (Phase 3 → 5)")
        console.print("  [cyan]4f[/cyan]. Run All (Force — skip pre-flight checks)")
        console.print("  [cyan]5[/cyan]. Status Check")
        console.print("  [cyan]6[/cyan]. Reconfigure")
        console.print("  [cyan]7[/cyan]. Troubleshoot")
        console.print("  [cyan]8[/cyan]. Teardown (Destroy K8s VMs)")
        console.print("  [cyan]0[/cyan]. Exit")
        console.print()

        choice = console.input("[bold]Select> [/bold]").strip()

        if choice == "1":
            run_phase3(config)
        elif choice == "2":
            _run_phase4(config, project_root)
        elif choice == "3":
            run_phase5(config)
        elif choice == "4":
            ok = run_phase3(config)
            if ok or prompt_confirm("Phase 3 had issues. Continue to Phase 4?", default=False):
                ok = _run_phase4(config, project_root)
            if ok or prompt_confirm("Phase 4 had issues. Continue to Phase 5?", default=False):
                run_phase5(config)
        elif choice == "4f":
            ok = run_phase3(config, force=True)
            if ok or prompt_confirm("Phase 3 had issues. Continue to Phase 4?", default=False):
                ok = _run_phase4(config, project_root, force=True)
            if ok or prompt_confirm("Phase 4 had issues. Continue to Phase 5?", default=False):
                run_phase5(config, force=True)
        elif choice == "5":
            _run_status_check(config)
        elif choice == "6":
            config = gather_config(project_root)
        elif choice == "7":
            run_troubleshoot(config)
        elif choice == "8":
            run_teardown(config)
        elif choice == "0":
            console.print("[dim]Goodbye![/dim]")
            break
        else:
            warn("Invalid selection")


@click.group(invoke_without_command=True)
@click.pass_context
@click.version_option(version=__version__)
def main(ctx: click.Context) -> None:
    """HomeLab Setup CLI — interactive Proxmox + Kubernetes bootstrap tool."""
    ctx.ensure_object(dict)
    ctx.obj["project_root"] = _find_project_root()

    if ctx.invoked_subcommand is None:
        _interactive_menu(ctx.obj["project_root"])


@main.command()
@click.option("--workers", "-w", type=int, default=None, help="Number of workers (0=k3s single-node)")
@click.option("--force", "-f", is_flag=True, default=False, help="Force re-run even if pre-flight checks pass")
@click.pass_context
def phase3(ctx: click.Context, workers: int | None, force: bool) -> None:
    """Phase 3: Provision K8s VMs on Proxmox."""
    project_root = ctx.obj["project_root"]
    config = load_config(project_root)

    if not config["proxmox"]["host"]:
        config = gather_config(project_root)
    elif workers is not None:
        config["cluster"]["worker_count"] = workers
        if workers == 0:
            config["cluster"]["mode"] = "k3s"
            config["cluster"]["worker_ips"] = []
        else:
            config["cluster"]["mode"] = "kubeadm"
        save_config(project_root, config)

    run_phase3(config, force=force)


@main.command()
@click.option("--force", "-f", is_flag=True, default=False, help="Force re-run even if pre-flight checks pass")
@click.pass_context
def phase4(ctx: click.Context, force: bool) -> None:
    """Phase 4: Install Kubernetes (k3s or kubeadm)."""
    project_root = ctx.obj["project_root"]
    config = load_config(project_root)

    if not config["proxmox"]["host"]:
        config = gather_config(project_root)

    _run_phase4(config, project_root, force=force)


@main.command()
@click.option("--force", "-f", is_flag=True, default=False, help="Force re-run even if pre-flight checks pass")
@click.pass_context
def phase5(ctx: click.Context, force: bool) -> None:
    """Phase 5: Bootstrap Cluster Services."""
    project_root = ctx.obj["project_root"]
    config = load_config(project_root)

    if not config["proxmox"]["host"]:
        config = gather_config(project_root)

    run_phase5(config, force=force)


@main.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Quick cluster status check."""
    project_root = ctx.obj["project_root"]
    config = load_config(project_root)
    _run_status_check(config)


@main.command()
@click.pass_context
def configure(ctx: click.Context) -> None:
    """Interactively reconfigure settings."""
    project_root = ctx.obj["project_root"]
    gather_config(project_root)


@main.command()
@click.pass_context
def troubleshoot(ctx: click.Context) -> None:
    """Interactive troubleshooting for cluster issues."""
    project_root = ctx.obj["project_root"]
    config = load_config(project_root)
    run_troubleshoot(config)


@main.command()
@click.option("--template", "-t", is_flag=True, help="Also delete the VM template")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def teardown(ctx: click.Context, template: bool, yes: bool) -> None:
    """Teardown: Destroy all K8s VMs on Proxmox."""
    project_root = ctx.obj["project_root"]
    config = load_config(project_root)

    if not config["proxmox"]["host"]:
        error("No Proxmox configuration found. Run 'setup-cli configure' first.")
        return

    run_teardown(config, delete_template=template, force=yes)


@main.command()
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def fix_cilium(ctx: click.Context, yes: bool) -> None:
    """Fix Cilium pod CIDR mismatch and restart dependent services."""
    from homelab_setup.troubleshoot import _get_kubeadm_pod_cidr, _attempt_heal
    from homelab_setup.utils import check_local_tool, info, error, success, prompt_confirm

    project_root = ctx.obj["project_root"]
    config = load_config(project_root)

    kubeadm_cidr = _get_kubeadm_pod_cidr()
    if not kubeadm_cidr:
        error("Could not detect kubeadm pod CIDR")
        return

    info(f"Detected pod CIDR: {kubeadm_cidr}")

    if not check_local_tool("helm"):
        error("helm not found — required to upgrade Cilium")
        return

    if not yes and not prompt_confirm("Apply Cilium fixes?", default=True):
        info("Aborted")
        return

    # 1. Upgrade Cilium with correct pod CIDR
    heal_cmd = (
        f"helm upgrade cilium cilium/cilium --namespace kube-system "
        f"--set operator.replicas=1 "
        f"--set ipam.operator.clusterPoolIPv4PodCIDRList={kubeadm_cidr} "
        f"--reuse-values"
    )
    _attempt_heal("Upgrade Cilium with correct pod CIDR", heal_cmd)

    # 2. Restart Cilium agents
    _attempt_heal("Restart Cilium agents", "kubectl rollout restart daemonset cilium -n kube-system")

    # 3. Restart CoreDNS
    _attempt_heal("Restart CoreDNS", "kubectl rollout restart deployment coredns -n kube-system")

    # 4. Restart ingress-nginx if installed
    rc, _, _ = run_local("kubectl get deployment ingress-nginx-controller -n ingress-nginx 2>/dev/null", check=False)
    if rc == 0:
        _attempt_heal("Restart ingress-nginx", "kubectl rollout restart deployment ingress-nginx-controller -n ingress-nginx")
    else:
        info("ingress-nginx not found — skipping")

    success("Cilium fix commands completed")
