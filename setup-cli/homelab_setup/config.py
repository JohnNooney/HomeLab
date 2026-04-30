"""Configuration management — load, save, and prompt for settings."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import yaml

from homelab_setup.utils import (
    console,
    display_config_table,
    info,
    prompt_choice,
    prompt_confirm,
    prompt_int,
    prompt_text,
    warn,
)

CONFIG_FILENAME = "config.yml"

DEFAULT_CONFIG: dict[str, Any] = {
    "proxmox": {
        "host": "",
        "user": "root",
        "ssh_key": "~/.ssh/homelab-dev",
    },
    "cluster": {
        "mode": "k3s",
        "control_plane_ip": "192.168.100.21",
        "worker_count": 0,
        "worker_ips": [],
        "network_gateway": "192.168.100.1",
        "network_subnet": "192.168.100.0/24",
        "dns": "8.8.8.8",
        "cni": "flannel",
        "template_id": 9000,
        "vm_start_id": 101,
        "cloud_image_url": "https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.img",
        "control_plane_cores": 2,
        "control_plane_memory": 4096,
        "worker_cores": 1,
        "worker_memory": 2048,
    },
}

WORKER_IP_MAP = {
    1: ["192.168.100.31"],
    2: ["192.168.100.31", "192.168.100.32"],
    3: ["192.168.100.31", "192.168.100.32", "192.168.100.33"],
}


def _config_path(project_root: str) -> str:
    """Return the path to the config file."""
    return os.path.join(project_root, "setup-cli", CONFIG_FILENAME)


def load_config(project_root: str) -> dict[str, Any]:
    """Load config from YAML file, returning defaults if not found."""
    path = _config_path(project_root)
    if os.path.exists(path):
        with open(path, "r") as f:
            data = yaml.safe_load(f) or {}
        # Merge with defaults to fill any missing keys
        merged = _deep_merge(DEFAULT_CONFIG, data)
        return merged
    return _deep_copy(DEFAULT_CONFIG)


def save_config(project_root: str, config: dict[str, Any]) -> None:
    """Save config to YAML file."""
    path = _config_path(project_root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)


def gather_config(project_root: str) -> dict[str, Any]:
    """Interactively gather configuration, using saved values as defaults."""
    config = load_config(project_root)
    px = config["proxmox"]
    cl = config["cluster"]

    console.print("\n[bold]Proxmox Node Configuration[/bold]")
    px["host"] = prompt_text("Proxmox node IP", default=px["host"])
    px["user"] = prompt_text("Proxmox SSH user", default=px["user"])
    px["ssh_key"] = prompt_text("SSH key path", default=px["ssh_key"])

    console.print("\n[bold]Cluster Configuration[/bold]")
    cl["worker_count"] = prompt_int(
        "Number of worker nodes (0 = single-node k3s)",
        default=cl["worker_count"],
        min_val=0,
        max_val=3,
    )

    if cl["worker_count"] == 0:
        cl["mode"] = "k3s"
        cl["cni"] = "flannel"
        cl["worker_ips"] = []
        info("Single-node mode: will use k3s (batteries-included)")
    else:
        cl["mode"] = "kubeadm"
        cl["worker_ips"] = WORKER_IP_MAP.get(cl["worker_count"], [])
        info(f"Multi-node mode: will use kubeadm via Ansible ({cl['worker_count']} workers)")

    cl["control_plane_ip"] = prompt_text(
        "Control plane VM IP", default=cl["control_plane_ip"]
    )
    cl["network_gateway"] = prompt_text(
        "Network gateway", default=cl["network_gateway"]
    )
    cl["dns"] = prompt_text("DNS server", default=cl["dns"])

    console.print("\n[bold]VM Resource Configuration[/bold]")
    cl["control_plane_cores"] = prompt_int(
        "Control plane CPU cores", default=cl.get("control_plane_cores", 2), min_val=1, max_val=16
    )
    cl["control_plane_memory"] = prompt_int(
        "Control plane memory (MB)", default=cl.get("control_plane_memory", 4096), min_val=1024, max_val=65536
    )
    if cl["worker_count"] > 0:
        cl["worker_cores"] = prompt_int(
            "Worker node CPU cores", default=cl.get("worker_cores", 1), min_val=1, max_val=16
        )
        cl["worker_memory"] = prompt_int(
            "Worker node memory (MB)", default=cl.get("worker_memory", 2048), min_val=1024, max_val=65536
        )

    if cl["worker_count"] > 0:
        console.print("\n[bold]Worker IPs[/bold]")
        for i in range(cl["worker_count"]):
            default_ip = cl["worker_ips"][i] if i < len(cl["worker_ips"]) else f"192.168.100.{31 + i}"
            cl["worker_ips"][i] = prompt_text(f"Worker {i + 1} IP", default=default_ip)
        # Trim excess
        cl["worker_ips"] = cl["worker_ips"][: cl["worker_count"]]

    # Show summary
    console.print()
    display_config_table("Configuration Summary", {
        "Proxmox Host": px["host"],
        "SSH User": px["user"],
        "SSH Key": px["ssh_key"],
        "Mode": cl["mode"],
        "Control Plane IP": cl["control_plane_ip"],
        "Control Plane Resources": f"{cl.get('control_plane_cores', 2)} cores / {cl.get('control_plane_memory', 4096)} MB",
        "Workers": cl["worker_count"],
        "Worker IPs": ", ".join(cl["worker_ips"]) if cl["worker_ips"] else "N/A",
        "Worker Resources": f"{cl.get('worker_cores', 1)} cores / {cl.get('worker_memory', 2048)} MB" if cl["worker_count"] > 0 else "N/A",
        "Gateway": cl["network_gateway"],
        "DNS": cl["dns"],
    })

    if prompt_confirm("Save this configuration?", default=True):
        save_config(project_root, config)

    return config


def get_all_vm_ips(config: dict[str, Any]) -> list[str]:
    """Return list of all VM IPs (control plane + workers)."""
    ips = [config["cluster"]["control_plane_ip"]]
    ips.extend(config["cluster"]["worker_ips"])
    return ips


def get_vm_definitions(config: dict[str, Any]) -> list[dict]:
    """Build VM definition list from config."""
    cl = config["cluster"]
    vms = [
        {
            "id": cl.get("vm_start_id", 101),
            "name": "k8s-control-01",
            "ip": cl["control_plane_ip"],
            "role": "control-plane",
            "cores": cl.get("control_plane_cores", 2),
            "memory": cl.get("control_plane_memory", 4096),
        }
    ]
    worker_start_id = 201
    for i, ip in enumerate(cl["worker_ips"]):
        vms.append(
            {
                "id": worker_start_id + i,
                "name": f"k8s-worker-{i + 1:02d}",
                "ip": ip,
                "role": "worker",
                "cores": cl.get("worker_cores", 1),
                "memory": cl.get("worker_memory", 2048),
            }
        )
    return vms


def _deep_merge(defaults: dict, overrides: dict) -> dict:
    """Recursively merge overrides into defaults."""
    result = defaults.copy()
    for key, val in overrides.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def _deep_copy(d: dict) -> dict:
    """Simple deep copy for nested dicts/lists."""
    import copy
    return copy.deepcopy(d)
