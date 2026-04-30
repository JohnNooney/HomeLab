# HomeLab Setup CLI

Interactive Python CLI tool for bootstrapping a Kubernetes cluster on Proxmox. Runs from your Mac, SSHs into the Proxmox node, provisions VMs, and installs Kubernetes end-to-end.

## Two Paths

| Topology | K8s Distribution | Phase 4 Method |
|---|---|---|
| **Single-node** (0 workers) | k3s | Direct SSH install (no Ansible) |
| **Multi-node** (1-3 workers) | kubeadm | Ansible playbooks |

k3s includes Flannel CNI, CoreDNS, local-path-provisioner, and Traefik — all bundled.

## Quick Start

```bash
cd setup-cli

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e .

# Run interactive menu
homelab-setup
```

## CLI Commands

```bash
# Interactive menu (default)
homelab-setup

# Run specific phases
homelab-setup phase3 --workers 0    # Provision single VM on Proxmox
homelab-setup phase4                 # Install k3s or kubeadm
homelab-setup phase5                 # Bootstrap cluster services

# Force re-run (skip pre-flight checks)
homelab-setup phase3 --force
homelab-setup phase4 -f
homelab-setup phase5 -f

# Utilities
homelab-setup status                 # Quick cluster health check
homelab-setup configure              # Reconfigure settings
```

## What Each Phase Does

### Phase 3: Provision K8s VMs on Proxmox
1. Generate SSH keypair (`~/.ssh/homelab-dev`) if not exists
2. Download Ubuntu 22.04 cloud image to Proxmox node
3. Create VM template (cloud-init enabled)
4. Clone VMs from template with static IPs
5. Verify SSH connectivity to all VMs

### Phase 4: Install Kubernetes
**Single-node (k3s):**
- Installs k3s via `curl -sfL https://get.k3s.io | sh -`
- Waits for node Ready
- Fetches and rewrites kubeconfig

**Multi-node (kubeadm):**
- Generates Ansible inventory at `ansible/inventory/home.yml`
- Runs Ansible playbooks (all-at-once or step-by-step)

### Phase 5: Bootstrap Cluster Services
**k3s:** Validates bundled services, optionally replaces Traefik with nginx-ingress

**kubeadm:** Deploys CNI (Calico/Cilium), nginx-ingress, local-path-provisioner

Both paths run a validation checklist at the end.

## Pre-flight Checks

Each phase runs automated completion checks before executing. If all checks pass the phase is **auto-skipped** — no work is repeated.

| Phase | Checks |
|---|---|
| **Phase 3** | SSH key exists, cloud image on Proxmox, VM template exists, all VMs running, all VMs SSH-reachable |
| **Phase 4 (k3s)** | k3s installed on control plane, node Ready, kubeconfig exists locally, local kubectl works |
| **Phase 4 (kubeadm)** | Ansible installed, inventory file exists, expected node count visible, all nodes Ready |
| **Phase 5 (k3s)** | Nodes Ready, system pods healthy, ingress controller present, StorageClass exists |
| **Phase 5 (kubeadm)** | Kubeconfig exists, nodes Ready, CNI pods running, ingress running, default StorageClass exists |

Use `--force` / `-f` to bypass pre-flight checks and re-run a phase regardless. In the interactive menu, option `4f` runs all phases with force.

## Configuration

Settings are persisted in `setup-cli/config.yml` so re-runs skip prompts:

```yaml
proxmox:
  host: 192.168.1.100
  user: root
  ssh_key: ~/.ssh/homelab-dev
cluster:
  mode: k3s
  control_plane_ip: 192.168.100.21
  worker_count: 0
  worker_ips: []
  network_gateway: 192.168.100.1
  dns: "8.8.8.8"
```

## Prerequisites

- **Python 3.9+**
- **SSH access** to your Proxmox node
- **kubectl** (for Phase 5 validation)
- **Helm 3+** (for kubeadm path CNI/ingress, or optional nginx swap on k3s)
- **Ansible** (only for multi-node/kubeadm path)
