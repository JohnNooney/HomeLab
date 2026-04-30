"""Pre-flight completion checks for each phase."""

from __future__ import annotations

import os
import shutil
from typing import Any

from homelab_setup.ssh import SSHClient, wait_for_ssh
from homelab_setup.utils import (
    display_preflight_table,
    info,
    run_local,
    success,
    warn,
)

CheckResult = list[tuple[str, bool]]


def _all_passed(results: CheckResult) -> bool:
    """Return True if every check in the results list passed."""
    return all(passed for _, passed in results)


def evaluate_preflight(phase_name: str, results: CheckResult, force: bool) -> bool:
    """Display preflight results and decide whether to skip.

    Returns True if the phase should be skipped (already complete).
    """
    display_preflight_table(phase_name, results)

    if _all_passed(results):
        if force:
            warn(f"{phase_name} already complete but --force specified, re-running")
            return False
        success(f"{phase_name} already complete — skipping")
        return True

    return False


# ─── Phase 3 ────────────────────────────────────────────────────────────────


def check_phase3(config: dict[str, Any]) -> CheckResult:
    """Check whether Phase 3 (VM provisioning) is already complete."""
    from homelab_setup.config import get_vm_definitions

    results: CheckResult = []
    px = config["proxmox"]
    cl = config["cluster"]

    # 1. SSH key exists locally
    key_path = os.path.expanduser(px["ssh_key"])
    results.append(("SSH key exists locally", os.path.exists(key_path)))

    # Need SSH to Proxmox for remaining checks
    try:
        with SSHClient(host=px["host"], user=px["user"], key_path=px["ssh_key"]) as ssh:
            # 2. Cloud image on Proxmox
            image_path = f"/var/lib/vz/template/iso/jammy-server-cloudimg-amd64.img"
            results.append(("Cloud image on Proxmox", ssh.file_exists(image_path)))

            # 3. VM template exists
            template_id = cl.get("template_id", 9000)
            rc, _, _ = ssh.run(f"qm status {template_id}", check=False)
            results.append((f"VM template {template_id} exists", rc == 0))

            # 4. All VMs exist
            vms = get_vm_definitions(config)
            for vm in vms:
                rc, stdout, _ = ssh.run(f"qm status {vm['id']}", check=False)
                running = rc == 0 and "running" in stdout.lower()
                results.append((f"VM {vm['name']} ({vm['id']}) running", running))

    except Exception:
        results.append(("Proxmox SSH reachable", False))
        return results

    # 5. All VMs SSH-reachable (quick single-attempt check)
    vms = get_vm_definitions(config)
    for vm in vms:
        reachable = wait_for_ssh(
            host=vm["ip"],
            user="ubuntu",
            key_path=px["ssh_key"],
            retries=1,
            delay=2,
        )
        results.append((f"VM {vm['name']} SSH reachable", reachable))

    return results


# ─── Phase 4 k3s ────────────────────────────────────────────────────────────


def check_phase4_k3s(config: dict[str, Any]) -> CheckResult:
    """Check whether Phase 4 k3s is already complete."""
    results: CheckResult = []
    cp_ip = config["cluster"]["control_plane_ip"]
    key_path = config["proxmox"]["ssh_key"]

    # 1–2. SSH checks on control plane
    try:
        with SSHClient(host=cp_ip, user="ubuntu", key_path=key_path) as ssh:
            rc, _, _ = ssh.run("which k3s", check=False)
            results.append(("k3s installed on control plane", rc == 0))

            rc, stdout, _ = ssh.run(
                "sudo k3s kubectl get nodes --no-headers 2>/dev/null", check=False
            )
            node_ready = rc == 0 and "Ready" in stdout and "NotReady" not in stdout
            results.append(("k3s node Ready", node_ready))
    except Exception:
        results.append(("k3s installed on control plane", False))
        results.append(("k3s node Ready", False))

    # 3. Kubeconfig exists locally
    kubeconfig = os.path.expanduser("~/.kube/config")
    results.append(("Kubeconfig exists locally", os.path.exists(kubeconfig)))

    # 4. Local kubectl works
    rc, _, _ = run_local("kubectl get nodes", check=False)
    results.append(("Local kubectl access", rc == 0))

    return results


# ─── Phase 4 kubeadm ────────────────────────────────────────────────────────


def check_phase4_kubeadm(config: dict[str, Any], project_root: str) -> CheckResult:
    """Check whether Phase 4 kubeadm is already complete."""
    results: CheckResult = []
    cl = config["cluster"]

    # 1. Ansible installed
    results.append(("Ansible installed", shutil.which("ansible") is not None))

    # 2. Inventory file exists
    inventory_path = os.path.join(project_root, "ansible", "inventory", "home.yml")
    results.append(("Ansible inventory exists", os.path.exists(inventory_path)))

    # 3–4. kubectl node checks
    expected_count = 1 + cl["worker_count"]
    rc, stdout, _ = run_local("kubectl get nodes --no-headers", check=False)
    if rc == 0:
        lines = [l for l in stdout.strip().splitlines() if l.strip()]
        results.append((
            f"All nodes visible ({len(lines)}/{expected_count})",
            len(lines) == expected_count,
        ))
        has_not_ready = any("NotReady" in l for l in lines)
        results.append(("All nodes Ready", not has_not_ready and len(lines) > 0))
    else:
        results.append((f"All nodes visible (0/{expected_count})", False))
        results.append(("All nodes Ready", False))

    return results


# ─── Phase 5 k3s ────────────────────────────────────────────────────────────


def check_phase5_k3s(config: dict[str, Any]) -> CheckResult:
    """Check whether Phase 5 k3s bootstrapping is already complete."""
    results: CheckResult = []

    # 1. Nodes Ready
    rc, stdout, _ = run_local("kubectl get nodes --no-headers", check=False)
    nodes_ready = rc == 0 and "NotReady" not in stdout and stdout.strip() != ""
    results.append(("Nodes Ready", nodes_ready))

    # 2. System pods healthy
    rc, stdout, _ = run_local(
        "kubectl get pods -n kube-system --field-selector=status.phase!=Running,status.phase!=Succeeded --no-headers 2>/dev/null",
        check=False,
    )
    results.append(("System pods healthy", rc == 0 and stdout.strip() == ""))

    # 3. Ingress present (traefik or nginx)
    rc_t, _, _ = run_local(
        "kubectl get pods -n kube-system -l app.kubernetes.io/name=traefik --no-headers 2>/dev/null",
        check=False,
    )
    rc_n, _, _ = run_local(
        "kubectl get pods -n ingress-nginx --no-headers 2>/dev/null",
        check=False,
    )
    results.append(("Ingress controller present", rc_t == 0 or rc_n == 0))

    # 4. StorageClass exists
    rc, stdout, _ = run_local("kubectl get storageclass --no-headers 2>/dev/null", check=False)
    results.append(("StorageClass exists", rc == 0 and stdout.strip() != ""))

    return results


# ─── Phase 5 kubeadm ────────────────────────────────────────────────────────


def check_phase5_kubeadm(config: dict[str, Any]) -> CheckResult:
    """Check whether Phase 5 kubeadm bootstrapping is already complete."""
    results: CheckResult = []

    # 1. Kubeconfig exists
    kubeconfig = os.path.expanduser("~/.kube/config")
    results.append(("Kubeconfig exists", os.path.exists(kubeconfig)))

    # 2. All nodes Ready
    rc, stdout, _ = run_local("kubectl get nodes --no-headers", check=False)
    nodes_ready = rc == 0 and "NotReady" not in stdout and stdout.strip() != ""
    results.append(("All nodes Ready", nodes_ready))

    # 3. CNI pods running (calico or cilium)
    rc_cal, stdout_cal, _ = run_local(
        "kubectl get pods -n kube-system -l k8s-app=calico-node --no-headers 2>/dev/null",
        check=False,
    )
    rc_cil, stdout_cil, _ = run_local(
        "kubectl get pods -n kube-system -l app.kubernetes.io/name=cilium-agent --no-headers 2>/dev/null",
        check=False,
    )
    cni_ok = (rc_cal == 0 and stdout_cal.strip() != "") or (rc_cil == 0 and stdout_cil.strip() != "")
    results.append(("CNI pods running", cni_ok))

    # 4. Ingress pods running
    rc, stdout, _ = run_local(
        "kubectl get pods -n ingress-nginx --no-headers 2>/dev/null", check=False
    )
    results.append(("Ingress controller running", rc == 0 and stdout.strip() != ""))

    # 5. StorageClass with default
    rc, stdout, _ = run_local("kubectl get storageclass --no-headers 2>/dev/null", check=False)
    has_default = rc == 0 and "(default)" in stdout
    results.append(("Default StorageClass exists", has_default))

    return results
