"""Phase 4 — Path B: kubeadm installation via Ansible for multi-node clusters."""

from __future__ import annotations

import os
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
    """Check that Ansible is installed locally."""
    step(1, "Check prerequisites")

    if not check_local_tool("ansible"):
        error("ansible not found in PATH. Install Ansible first:")
        info("  brew install ansible")
        info("  or: pip install ansible")
        return False

    if not check_local_tool("ansible-playbook"):
        error("ansible-playbook not found in PATH")
        return False

    success("Ansible is installed")
    return True


def step_generate_inventory(config: dict[str, Any], project_root: str) -> bool:
    """Generate Ansible inventory file at ansible/inventory/home.yml."""
    step(2, "Generate Ansible inventory")

    cl = config["cluster"]
    px = config["proxmox"]
    inventory_path = os.path.join(project_root, "ansible", "inventory", "home.yml")

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
