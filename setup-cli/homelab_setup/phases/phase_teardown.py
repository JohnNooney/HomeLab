"""Teardown phase: Delete Kubernetes VMs from Proxmox."""

from __future__ import annotations

from typing import Any

from homelab_setup.config import get_vm_definitions
from homelab_setup.ssh import SSHClient
from homelab_setup.utils import (
    console,
    display_vm_table,
    error,
    info,
    phase_header,
    prompt_confirm,
    step,
    success,
    warn,
)


def run_teardown(config: dict[str, Any], delete_template: bool = False, force: bool = False) -> bool:
    """Run teardown: stop and destroy all K8s VMs on Proxmox.

    Args:
        config: The configuration dictionary
        delete_template: Whether to also delete the VM template
        force: Skip confirmation prompts if True

    Returns:
        True if teardown succeeded
    """
    phase_header("Teardown", "Destroy Kubernetes VMs on Proxmox")

    px = config["proxmox"]
    cl = config["cluster"]
    template_id = cl.get("template_id", 9000)

    # Get VM definitions
    vms = get_vm_definitions(config)

    if not vms:
        warn("No VMs defined in configuration")
        return False

    # Display VMs to be deleted
    console.print("\n[bold red]The following VMs will be DESTROYED:[/bold red]")
    display_vm_table(vms)

    if delete_template:
        console.print(f"\n[bold red]Template VM {template_id} will also be DESTROYED[/bold red]")

    console.print()

    if not force and not prompt_confirm("Proceed with teardown? This action is IRREVERSIBLE!", default=False):
        warn("Teardown cancelled by user")
        return False

    # Connect to Proxmox and destroy VMs
    ok = True
    try:
        with SSHClient(host=px["host"], user=px["user"], key_path=px["ssh_key"]) as ssh:
            # First, stop and destroy all K8s VMs
            for vm in vms:
                vm_id = vm["id"]
                vm_name = vm["name"]

                # Check if VM exists
                rc, stdout, _ = ssh.run(f"qm status {vm_id}", check=False)
                if rc != 0:
                    info(f"VM {vm_name} ({vm_id}) does not exist, skipping")
                    continue

                step(1, f"Destroying VM {vm_name} ({vm_id})")

                # Stop VM if running
                if "running" in stdout.lower():
                    info(f"Stopping VM {vm_name} ({vm_id})...")
                    ssh.run(f"qm stop {vm_id}", timeout=60, check=False)

                # Destroy VM
                info(f"Destroying VM {vm_name} ({vm_id})...")
                rc, _, stderr = ssh.run(f"qm destroy {vm_id} --destroy-unreferenced-disks --purge", timeout=120, check=False)
                if rc == 0:
                    success(f"VM {vm_name} ({vm_id}) destroyed")
                else:
                    error(f"Failed to destroy VM {vm_name} ({vm_id}): {stderr}")
                    ok = False

            # Optionally destroy template
            if delete_template:
                step(2, f"Destroying template {template_id}")

                rc, stdout, _ = ssh.run(f"qm status {template_id}", check=False)
                if rc == 0:
                    if "running" in stdout.lower():
                        info(f"Stopping template {template_id}...")
                        ssh.run(f"qm stop {template_id}", timeout=60, check=False)

                    info(f"Destroying template {template_id}...")
                    rc, _, stderr = ssh.run(
                        f"qm destroy {template_id} --destroy-unreferenced-disks --purge",
                        timeout=120,
                        check=False,
                    )
                    if rc == 0:
                        success(f"Template {template_id} destroyed")
                    else:
                        error(f"Failed to destroy template {template_id}: {stderr}")
                        ok = False
                else:
                    info(f"Template {template_id} does not exist, skipping")

    except Exception as exc:
        error(f"Failed to connect to Proxmox: {exc}")
        return False

    if ok:
        success("Teardown complete — all VMs destroyed")
    else:
        error("Teardown completed with errors")

    return ok
