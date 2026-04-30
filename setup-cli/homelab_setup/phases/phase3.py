"""Phase 3: Kubernetes VM Provisioning on Proxmox."""

from __future__ import annotations

import os
import time
from typing import Any

from rich.progress import Progress, SpinnerColumn, TextColumn

from homelab_setup.config import get_vm_definitions
from homelab_setup.preflight import check_phase3, evaluate_preflight
from homelab_setup.ssh import SSHClient, generate_ssh_keypair, wait_for_ssh
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

CLOUD_IMAGE_NAME = "jammy-server-cloudimg-amd64.img"
CLOUD_IMAGE_DIR = "/var/lib/vz/template/iso"


def run_phase3(config: dict[str, Any], force: bool = False) -> bool:
    """Run all Phase 3 sub-steps.

    Returns True if all steps succeeded.
    """
    phase_header("Phase 3", "Provision Kubernetes VMs on Proxmox")

    results = check_phase3(config)
    if evaluate_preflight("Phase 3", results, force):
        return True

    vms = get_vm_definitions(config)
    display_vm_table(vms)
    console.print()

    if not prompt_confirm("Proceed with VM provisioning?"):
        warn("Phase 3 skipped by user")
        return False

    ok = True
    ok = step_ssh_key_setup(config) and ok
    ok = step_download_cloud_image(config) and ok
    ok = step_create_template(config) and ok
    ok = step_create_vms(config) and ok
    ok = step_verify_connectivity(config) and ok

    if ok:
        success("Phase 3 complete — all VMs provisioned and reachable")
    else:
        error("Phase 3 completed with errors")

    return ok


def step_ssh_key_setup(config: dict[str, Any]) -> bool:
    """Step 1: Generate SSH keypair if not exists."""
    step(1, "SSH key setup")
    key_path = config["proxmox"]["ssh_key"]
    expanded = os.path.expanduser(key_path)

    if os.path.exists(expanded):
        success(f"SSH key already exists: {key_path}")
        with open(f"{expanded}.pub", "r") as f:
            pub_key = f.read().strip()
        info(f"Public key: {pub_key[:60]}...")
        return True

    info(f"Generating SSH keypair at {key_path}")
    try:
        pub_key = generate_ssh_keypair(key_path)
        success(f"SSH keypair generated: {key_path}")
        info(f"Public key: {pub_key[:60]}...")
        return True
    except Exception as exc:
        error(f"Failed to generate SSH key: {exc}")
        return False


def step_download_cloud_image(config: dict[str, Any]) -> bool:
    """Step 2: Download Ubuntu cloud image on Proxmox node."""
    step(2, "Download Ubuntu cloud image on Proxmox")

    px = config["proxmox"]
    cl = config["cluster"]
    image_url = cl.get("cloud_image_url", f"https://cloud-images.ubuntu.com/jammy/current/{CLOUD_IMAGE_NAME}")
    remote_image_path = f"{CLOUD_IMAGE_DIR}/{CLOUD_IMAGE_NAME}"

    try:
        with SSHClient(host=px["host"], user=px["user"], key_path=px["ssh_key"]) as ssh:
            if ssh.file_exists(remote_image_path):
                success("Cloud image already present on Proxmox node")
                return True

            info(f"Downloading cloud image to Proxmox node...")
            ssh.run(f"mkdir -p {CLOUD_IMAGE_DIR}", timeout=30)
            ssh.run(
                f"wget -q --show-progress -O {remote_image_path} {image_url}",
                timeout=600,
                stream_output=True,
            )
            success("Cloud image downloaded")
            return True
    except Exception as exc:
        error(f"Failed to download cloud image: {exc}")
        return False


def step_create_template(config: dict[str, Any]) -> bool:
    """Step 3: Create VM template on Proxmox."""
    step(3, "Create VM template on Proxmox")

    px = config["proxmox"]
    cl = config["cluster"]
    template_id = cl.get("template_id", 9000)

    try:
        with SSHClient(host=px["host"], user=px["user"], key_path=px["ssh_key"]) as ssh:
            # Check if template already exists
            rc, _, _ = ssh.run(f"qm status {template_id}", check=False)
            if rc == 0:
                success(f"Template {template_id} already exists")
                return True

            info(f"Creating VM template (ID: {template_id})...")

            commands = [
                f"qm create {template_id} --name ubuntu-k8s-template --memory 4096 --cores 1 --net0 virtio,bridge=vmbr0",
                f"qm importdisk {template_id} {CLOUD_IMAGE_DIR}/{CLOUD_IMAGE_NAME} local-lvm",
                f"qm set {template_id} --scsihw virtio-scsi-pci --scsi0 local-lvm:vm-{template_id}-disk-0",
                f"qm set {template_id} --ide2 local-lvm:cloudinit",
                f"qm set {template_id} --boot c --bootdisk scsi0",
                f"qm set {template_id} --serial0 socket --vga serial0",
                f"qm set {template_id} --agent enabled=1",
                f"qm template {template_id}",
            ]

            for cmd in commands:
                ssh.run(cmd, timeout=120, stream_output=True)

            success(f"Template {template_id} created")
            return True
    except Exception as exc:
        error(f"Failed to create template: {exc}")
        return False


def step_create_vms(config: dict[str, Any]) -> bool:
    """Step 4: Clone template and create K8s VMs."""
    step(4, "Create Kubernetes VMs")

    px = config["proxmox"]
    cl = config["cluster"]
    template_id = cl.get("template_id", 9000)
    vms = get_vm_definitions(config)
    key_path = os.path.expanduser(px["ssh_key"])
    pub_path = f"{key_path}.pub"

    if not os.path.exists(pub_path):
        error(f"Public key not found: {pub_path}")
        return False

    with open(pub_path, "r") as f:
        pub_key = f.read().strip()

    all_ok = True
    try:
        with SSHClient(host=px["host"], user=px["user"], key_path=px["ssh_key"]) as ssh:
            for vm in vms:
                vm_id = vm["id"]
                vm_name = vm["name"]
                vm_ip = vm["ip"]
                gateway = cl["network_gateway"]
                dns = cl["dns"]

                # Check if VM already exists
                rc, _, _ = ssh.run(f"qm status {vm_id}", check=False)
                if rc == 0:
                    info(f"VM {vm_name} ({vm_id}) already exists, skipping")
                    continue

                info(f"Creating VM {vm_name} ({vm_id}) — {vm_ip}")

                # Upload SSH public key to Proxmox for cloud-init
                remote_key_path = f"/tmp/ssh_key_{vm_id}.pub"
                ssh.upload_string(pub_key + "\n", remote_key_path)

                commands = [
                    f"qm clone {template_id} {vm_id} --name {vm_name} --full",
                    f"qm set {vm_id} --cores {vm['cores']}",
                    f"qm set {vm_id} --memory {vm['memory']}",
                    f"qm set {vm_id} --ipconfig0 ip={vm_ip}/24,gw={gateway}",
                    f"qm set {vm_id} --nameserver {dns}",
                    f"qm set {vm_id} --sshkeys {remote_key_path}",
                    f"qm set {vm_id} --ciuser ubuntu",
                    f"qm resize {vm_id} scsi0 +30G",
                    f"qm start {vm_id}",
                    f"rm -f {remote_key_path}",
                ]

                try:
                    for cmd in commands:
                        ssh.run(cmd, timeout=120, stream_output=True)
                    success(f"VM {vm_name} created and started")
                except Exception as exc:
                    error(f"Failed to create VM {vm_name}: {exc}")
                    all_ok = False

    except Exception as exc:
        error(f"Failed to connect to Proxmox: {exc}")
        return False

    return all_ok


def step_verify_connectivity(config: dict[str, Any]) -> bool:
    """Step 5: Wait for cloud-init and verify SSH connectivity to all VMs."""
    step(5, "Verify VM connectivity")

    px = config["proxmox"]
    vms = get_vm_definitions(config)

    info("Waiting for cloud-init to complete (this may take 2-3 minutes)...")

    all_ok = True
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        for vm in vms:
            task = progress.add_task(f"Waiting for {vm['name']} ({vm['ip']})...", total=None)
            reachable = wait_for_ssh(
                host=vm["ip"],
                user="ubuntu",
                key_path=px["ssh_key"],
                retries=20,
                delay=10,
            )
            progress.remove_task(task)

            if reachable:
                success(f"{vm['name']} ({vm['ip']}) — SSH reachable")
            else:
                error(f"{vm['name']} ({vm['ip']}) — SSH unreachable after retries")
                all_ok = False

    return all_ok
