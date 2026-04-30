"""Phase 4 — Path A: k3s installation for single-node clusters."""

from __future__ import annotations

import os
import time
from typing import Any

from homelab_setup.preflight import check_phase4_k3s, evaluate_preflight
from homelab_setup.ssh import SSHClient
from homelab_setup.utils import (
    console,
    error,
    info,
    phase_header,
    prompt_confirm,
    run_local,
    step,
    success,
    warn,
)

K3S_INSTALL_CMD = "curl -sfL https://get.k3s.io | sh -"


def run_phase4_k3s(config: dict[str, Any], force: bool = False) -> bool:
    """Install k3s on the single control-plane VM.

    Returns True if installation succeeded.
    """
    phase_header("Phase 4", "Install Kubernetes (k3s — single-node)")

    results = check_phase4_k3s(config)
    if evaluate_preflight("Phase 4 (k3s)", results, force):
        return True

    cp_ip = config["cluster"]["control_plane_ip"]
    key_path = config["proxmox"]["ssh_key"]

    info(f"Target: ubuntu@{cp_ip}")
    info("k3s includes: Flannel CNI, CoreDNS, local-path-provisioner, Traefik ingress")
    console.print()

    if not prompt_confirm("Install k3s on the control-plane VM?"):
        warn("Phase 4 skipped by user")
        return False

    ok = True
    ok = step_install_k3s(cp_ip, key_path) and ok
    ok = step_wait_for_node(cp_ip, key_path) and ok
    ok = step_fetch_kubeconfig(cp_ip, key_path) and ok
    ok = step_verify_local_kubectl(cp_ip) and ok

    if ok:
        success("Phase 4 complete — k3s installed and kubeconfig configured")
    else:
        error("Phase 4 completed with errors")

    return ok


def step_install_k3s(cp_ip: str, key_path: str) -> bool:
    """Step 1: Install k3s on the control-plane VM."""
    step(1, "Install k3s")

    try:
        with SSHClient(host=cp_ip, user="ubuntu", key_path=key_path) as ssh:
            # Check if k3s is already installed
            rc, stdout, _ = ssh.run("which k3s", check=False)
            if rc == 0:
                info("k3s is already installed")
                rc2, version_out, _ = ssh.run("k3s --version", check=False)
                if rc2 == 0:
                    info(f"Version: {version_out.strip()}")
                return True

            info("Installing k3s...")
            ssh.run(K3S_INSTALL_CMD, timeout=300, stream_output=True)
            success("k3s installed")
            return True
    except Exception as exc:
        error(f"Failed to install k3s: {exc}")
        return False


def step_wait_for_node(cp_ip: str, key_path: str) -> bool:
    """Step 2: Wait for the k3s node to become Ready."""
    step(2, "Wait for node Ready")

    try:
        with SSHClient(host=cp_ip, user="ubuntu", key_path=key_path) as ssh:
            for attempt in range(1, 31):
                rc, stdout, _ = ssh.run(
                    "sudo k3s kubectl get nodes --no-headers 2>/dev/null",
                    check=False,
                )
                if rc == 0 and "Ready" in stdout and "NotReady" not in stdout:
                    success(f"Node is Ready")
                    info(stdout.strip())
                    return True
                info(f"Waiting for node Ready (attempt {attempt}/30)...")
                time.sleep(10)

            error("Node did not become Ready within timeout")
            return False
    except Exception as exc:
        error(f"Failed to check node status: {exc}")
        return False


def step_fetch_kubeconfig(cp_ip: str, key_path: str) -> bool:
    """Step 3: Fetch k3s kubeconfig and rewrite server address."""
    step(3, "Fetch kubeconfig")

    kubeconfig_dir = os.path.expanduser("~/.kube")
    kubeconfig_path = os.path.join(kubeconfig_dir, "config")
    backup_path = os.path.join(kubeconfig_dir, "config.backup")

    try:
        with SSHClient(host=cp_ip, user="ubuntu", key_path=key_path) as ssh:
            # Read k3s kubeconfig
            rc, kubeconfig, _ = ssh.run("sudo cat /etc/rancher/k3s/k3s.yaml")
            if rc != 0:
                error("Failed to read k3s kubeconfig")
                return False

            # Rewrite server address from 127.0.0.1 to actual IP
            kubeconfig = kubeconfig.replace("127.0.0.1", cp_ip)
            kubeconfig = kubeconfig.replace("default", "homelab-k3s")

            # Backup existing kubeconfig if present
            os.makedirs(kubeconfig_dir, exist_ok=True)
            if os.path.exists(kubeconfig_path):
                info(f"Backing up existing kubeconfig to {backup_path}")
                with open(kubeconfig_path, "r") as f:
                    existing = f.read()
                with open(backup_path, "w") as f:
                    f.write(existing)

            # Write new kubeconfig
            with open(kubeconfig_path, "w") as f:
                f.write(kubeconfig)
            os.chmod(kubeconfig_path, 0o600)

            success(f"Kubeconfig written to {kubeconfig_path}")
            return True
    except Exception as exc:
        error(f"Failed to fetch kubeconfig: {exc}")
        return False


def step_verify_local_kubectl(cp_ip: str) -> bool:
    """Step 4: Verify kubectl works from the local machine."""
    step(4, "Verify local kubectl access")

    try:
        rc, stdout, stderr = run_local("kubectl get nodes", check=False)
        if rc == 0:
            success("kubectl access verified")
            for line in stdout.strip().splitlines():
                info(line)
            return True
        else:
            error(f"kubectl failed: {stderr.strip()}")
            return False
    except Exception as exc:
        error(f"kubectl verification failed: {exc}")
        return False
