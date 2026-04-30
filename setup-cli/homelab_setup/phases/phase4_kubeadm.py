"""Phase 4 — Path B: kubeadm installation via Ansible for multi-node clusters."""

from __future__ import annotations

import os
import platform
import shutil
from typing import Any

import yaml

from homelab_setup.preflight import check_phase4_kubeadm, evaluate_preflight
from homelab_setup.utils import (
    check_local_tool,
    console,
    error,
    info,
    phase_header,
    prompt_choice,
    prompt_confirm,
    run_local,
    step,
    success,
    warn,
)


def run_phase4_kubeadm(config: dict[str, Any], project_root: str, force: bool = False) -> bool:
    """Install Kubernetes via kubeadm using Ansible playbooks.

    Returns True if all steps succeeded.
    """
    phase_header("Phase 4", "Install Kubernetes (kubeadm — multi-node via Ansible)")

    results = check_phase4_kubeadm(config, project_root)
    if evaluate_preflight("Phase 4 (kubeadm)", results, force):
        return True

    cl = config["cluster"]
    info(f"Control plane: {cl['control_plane_ip']}")
    info(f"Workers: {', '.join(cl['worker_ips'])}")
    console.print()

    if not prompt_confirm("Proceed with kubeadm installation via Ansible?"):
        warn("Phase 4 skipped by user")
        return False

    ok = True
    ok = step_check_prerequisites() and ok
    if not ok:
        return False

    ok = step_generate_inventory(config, project_root) and ok
    ok = step_verify_ansible(config, project_root) and ok
    ok = step_run_playbooks(config, project_root) and ok

    if ok:
        success("Phase 4 complete — Kubernetes installed via Ansible")
    else:
        error("Phase 4 completed with errors")

    return ok


def step_check_prerequisites() -> bool:
    """Check that Ansible is installed locally. Install if missing."""
    step(1, "Check prerequisites")

    if check_local_tool("ansible") and check_local_tool("ansible-playbook"):
        success("Ansible is installed")
        return True

    warn("Ansible not found in PATH")

    system = platform.system()
    if system == "Darwin":  # macOS
        if check_local_tool("brew"):
            info("Installing Ansible via Homebrew...")
            try:
                run_local("brew install ansible", stream=True)
                success("Ansible installed via Homebrew")
                return True
            except Exception as exc:
                error(f"Homebrew install failed: {exc}")
        else:
            warn("Homebrew not found. Install from https://brew.sh")
    elif system == "Windows":
        if check_local_tool("choco"):
            info("Installing Ansible via Chocolatey...")
            try:
                run_local("choco install ansible -y", stream=True)
                success("Ansible installed via Chocolatey")
                # Refresh PATH
                os.environ["PATH"] = os.environ.get("PATH", "") + r";C:\ProgramData\chocolatey\bin"
                return True
            except Exception as exc:
                error(f"Chocolatey install failed: {exc}")
        else:
            warn("Chocolatey not found. Install from https://chocolatey.org")

    # Fallback to pip
    if check_local_tool("pip") or check_local_tool("pip3"):
        pip_cmd = "pip3" if check_local_tool("pip3") else "pip"
        if prompt_confirm("Install Ansible via pip?", default=True):
            info(f"Installing Ansible via {pip_cmd}...")
            try:
                run_local(f"{pip_cmd} install ansible", stream=True)
                success("Ansible installed via pip")
                return True
            except Exception as exc:
                error(f"pip install failed: {exc}")

    error("Could not install Ansible automatically. Please install manually:")
    info("  macOS:   brew install ansible")
    info("  Windows: choco install ansible")
    info("  pip:     pip3 install ansible")
    return False


def _load_existing_inventory(inventory_path: str) -> dict | None:
    """Load existing inventory file if it exists."""
    if not os.path.exists(inventory_path):
        return None
    try:
        with open(inventory_path, "r") as f:
            return yaml.safe_load(f)
    except Exception:
        return None


def _extract_inventory_info(inventory: dict | None) -> dict:
    """Extract node count and IPs from inventory."""
    if not inventory or "all" not in inventory:
        return {"control_plane_ip": None, "worker_ips": [], "worker_count": 0}

    children = inventory["all"].get("children", {})
    control_plane = children.get("control_plane", {}).get("hosts", {})
    workers = children.get("workers", {}).get("hosts", {})

    control_plane_ip = None
    if "k8s-control-01" in control_plane:
        control_plane_ip = control_plane["k8s-control-01"].get("ansible_host")

    worker_ips = []
    for name, data in workers.items():
        ip = data.get("ansible_host")
        if ip:
            worker_ips.append(ip)

    return {
        "control_plane_ip": control_plane_ip,
        "worker_ips": worker_ips,
        "worker_count": len(worker_ips),
    }


def step_generate_inventory(config: dict[str, Any], project_root: str) -> bool:
    """Generate Ansible inventory file at ansible/inventory/home.yml."""
    step(2, "Generate Ansible inventory")

    cl = config["cluster"]
    px = config["proxmox"]
    inventory_path = os.path.join(project_root, "ansible", "inventory", "home.yml")

    # Check existing inventory for sync issues
    existing = _load_existing_inventory(inventory_path)
    if existing:
        existing_info = _extract_inventory_info(existing)
        cli_info = {
            "control_plane_ip": cl["control_plane_ip"],
            "worker_ips": cl["worker_ips"],
            "worker_count": cl["worker_count"],
        }

        mismatch = False
        mismatches = []

        if existing_info["control_plane_ip"] != cli_info["control_plane_ip"]:
            mismatch = True
            mismatches.append(
                f"Control plane IP: {existing_info['control_plane_ip']} → {cli_info['control_plane_ip']}"
            )

        if existing_info["worker_count"] != cli_info["worker_count"]:
            mismatch = True
            mismatches.append(
                f"Worker count: {existing_info['worker_count']} → {cli_info['worker_count']}"
            )

        if set(existing_info["worker_ips"]) != set(cli_info["worker_ips"]):
            mismatch = True
            mismatches.append(
                f"Worker IPs: {existing_info['worker_ips']} → {cli_info['worker_ips']}"
            )

        if mismatch:
            warn("Existing inventory differs from CLI configuration")
            info(f"Inventory path: {inventory_path}")
            console.print("[yellow]Differences found:[/yellow]")
            for m in mismatches:
                console.print(f"  • {m}")

            if not prompt_confirm("Update inventory to match CLI configuration?", default=True):
                warn("Using existing inventory (may cause deployment issues)")
                return True

    # Build inventory structure
    inventory: dict = {
        "all": {
            "children": {
                "control_plane": {
                    "hosts": {
                        "k8s-control-01": {
                            "ansible_host": cl["control_plane_ip"],
                        }
                    }
                },
                "workers": {
                    "hosts": {}
                },
                "k8s_cluster": {
                    "children": {
                        "control_plane": {},
                        "workers": {},
                    }
                },
            },
            "vars": {
                "ansible_user": "ubuntu",
                "ansible_become": True,
                "ansible_python_interpreter": "/usr/bin/python3",
                "ansible_ssh_common_args": "-o StrictHostKeyChecking=no",
                "ansible_ssh_private_key_file": px["ssh_key"],
                "pod_cidr": cl.get("pod_network_cidr", "10.244.0.0/16"),
            },
        }
    }

    # Add worker hosts
    for i, ip in enumerate(cl["worker_ips"]):
        name = f"k8s-worker-{i + 1:02d}"
        inventory["all"]["children"]["workers"]["hosts"][name] = {
            "ansible_host": ip,
        }

    try:
        os.makedirs(os.path.dirname(inventory_path), exist_ok=True)
        with open(inventory_path, "w") as f:
            f.write("---\n")
            yaml.dump(inventory, f, default_flow_style=False, sort_keys=False)
        success(f"Inventory written to {inventory_path}")
        info(f"  Control plane: {cl['control_plane_ip']}")
        info(f"  Workers ({cl['worker_count']}): {', '.join(cl['worker_ips']) if cl['worker_ips'] else 'None'}")
        return True
    except Exception as exc:
        error(f"Failed to write inventory: {exc}")
        return False


def step_verify_ansible(config: dict[str, Any], project_root: str) -> bool:
    """Verify Ansible can reach all hosts."""
    step(3, "Verify Ansible connectivity")

    ansible_dir = os.path.join(project_root, "ansible")
    inventory_path = os.path.join(ansible_dir, "inventory", "home.yml")

    try:
        rc, stdout, stderr = run_local(
            f"ansible all -i {inventory_path} -m ping",
            cwd=ansible_dir,
            check=False,
            stream=True,
        )
        if rc == 0:
            success("All hosts reachable via Ansible")
            return True
        else:
            error("Some hosts unreachable. Check SSH connectivity and inventory.")
            if stderr.strip():
                info(stderr.strip())
            return False
    except Exception as exc:
        error(f"Ansible connectivity check failed: {exc}")
        return False


def step_run_playbooks(config: dict[str, Any], project_root: str) -> bool:
    """Run Ansible playbooks to install Kubernetes."""
    step(4, "Run Ansible playbooks")

    ansible_dir = os.path.join(project_root, "ansible")
    inventory_path = os.path.join(ansible_dir, "inventory", "home.yml")

    playbooks = [
        ("01-system-update.yml", "System updates and hardening"),
        ("02-networking.yml", "Kernel modules and networking"),
        ("03-disable-swap.yml", "Disable swap"),
        ("04-containerd.yml", "Install containerd runtime"),
        ("05-kubernetes-install.yml", "Install kubeadm, kubelet, kubectl"),
        ("06-control-plane-init.yml", "Initialize control plane"),
        ("07-workers-join.yml", "Join worker nodes"),
    ]

    mode = prompt_choice(
        "How to run playbooks?",
        ["All at once (site.yml)", "Step by step"],
        default="All at once (site.yml)",
    )

    if mode == "All at once (site.yml)":
        site_yml = os.path.join(ansible_dir, "playbooks", "site.yml")
        if os.path.exists(site_yml):
            info("Running site.yml...")
            rc, _, stderr = run_local(
                f"ansible-playbook -i {inventory_path} playbooks/site.yml",
                cwd=ansible_dir,
                check=False,
                stream=True,
            )
            if rc == 0:
                success("All playbooks completed")
                return True
            else:
                error(f"Playbook execution failed: {stderr.strip()}")
                return False
        else:
            warn("site.yml not found, falling back to step-by-step")
            mode = "Step by step"

    if mode == "Step by step":
        all_ok = True
        for pb_file, description in playbooks:
            pb_path = os.path.join(ansible_dir, "playbooks", pb_file)
            if not os.path.exists(pb_path):
                warn(f"Playbook {pb_file} not found, skipping")
                continue

            info(f"Running {pb_file} — {description}")
            if not prompt_confirm(f"Run {pb_file}?", default=True):
                info(f"Skipped {pb_file}")
                continue

            rc, _, stderr = run_local(
                f"ansible-playbook -i {inventory_path} playbooks/{pb_file}",
                cwd=ansible_dir,
                check=False,
                stream=True,
            )
            if rc == 0:
                success(f"{pb_file} completed")
            else:
                error(f"{pb_file} failed: {stderr.strip()}")
                all_ok = False
                if not prompt_confirm("Continue with remaining playbooks?", default=False):
                    return False

        return all_ok

    return True
