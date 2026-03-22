# Overview
This directory contains Ansible playbooks and roles for provisioning and configuring Ubuntu VMs running on Proxmox that will host the Kubernetes cluster.

## Phase 2: VM Provisioning (Ansible)

This phase prepares the Ubuntu VMs on Proxmox to run Kubernetes by installing dependencies, hardening the OS, and configuring networking.

### Prerequisites
- Proxmox VE hypervisor installed and configured
- Ubuntu 22.04 LTS (or later) VMs created on Proxmox
- SSH access to all VMs with sudo privileges
- Ansible >= 2.10 installed on control machine
- Inventory file configured with VM IP addresses and roles
- Python 3 installed on all target VMs

**Note**: VM creation on Proxmox can be done manually via the Proxmox web UI, CLI (`qm create`), or automated using Terraform with the Telmate Proxmox provider.

### Inventory Setup

Create or update `inventory/hosts.yml`:
```yaml
all:
  children:
    control_plane:
      hosts:
        master-01:
          ansible_host: 192.168.1.10
    workers:
      hosts:
        worker-01:
          ansible_host: 192.168.1.11
  vars:
    ansible_user: ubuntu
    ansible_become: yes
```

### Quick Start

```bash
# Navigate to ansible directory
cd ansible

# Run complete installation (recommended)
ansible-playbook -i inventory/hosts.yml playbooks/site.yml

# Or run the all-in-one playbook
ansible-playbook -i inventory/hosts.yml playbooks/k8s-install.yml
```

### Deployment Steps

#### 2.1 System Updates and Hardening
**Purpose**: Update packages, configure security settings, and harden the Ubuntu VMs.

```bash
cd ansible
ansible-playbook -i inventory/hosts.yml playbooks/01-system-update.yml
```

**Tasks Performed**:
- Update apt package cache and upgrade all packages
- Configure automatic security updates
- Set up UFW firewall with required ports
- Disable unnecessary services
- Configure SSH hardening (disable root login, key-only auth)
- Set up fail2ban for intrusion prevention
- Configure system timezone and NTP
- Set hostname and /etc/hosts entries

**Ports Opened**:
- 22 (SSH)
- 6443 (Kubernetes API - control plane only)
- 2379-2380 (etcd - control plane only)
- 10250-10252 (Kubelet, kube-scheduler, kube-controller)
- 30000-32767 (NodePort services)

#### 2.2 Networking Configuration
**Purpose**: Configure networking requirements for Kubernetes.

```bash
ansible-playbook -i inventory/hosts.yml playbooks/02-networking.yml
```

**Tasks Performed**:
- Enable IP forwarding (`net.ipv4.ip_forward = 1`)
- Configure bridge networking (`net.bridge.bridge-nf-call-iptables = 1`)
- Load required kernel modules:
  - `overlay`
  - `br_netfilter`
- Persist kernel modules in `/etc/modules-load.d/`
- Configure sysctl parameters for Kubernetes
- Disable IPv6 (optional, if not needed)
- Set up static IP addresses (if required)

#### 2.3 Disable Swap
**Purpose**: Disable swap as required by Kubernetes.

```bash
ansible-playbook -i inventory/hosts.yml playbooks/03-disable-swap.yml
```

**Tasks Performed**:
- Turn off all swap devices (`swapoff -a`)
- Remove swap entries from `/etc/fstab`
- Verify swap is disabled
- Persist configuration across reboots

#### 2.4 Container Runtime Installation
**Purpose**: Install and configure containerd as the container runtime.

```bash
ansible-playbook -i inventory/hosts.yml playbooks/04-containerd.yml
```

**Tasks Performed**:
- Install containerd and dependencies
- Configure containerd with systemd cgroup driver
- Create `/etc/containerd/config.toml` with proper settings
- Enable and start containerd service
- Install CNI plugins
- Configure containerd to use systemd cgroup driver
- Verify containerd installation

**Configuration**:
```toml
[plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runc.options]
  SystemdCgroup = true
```

#### 2.5 Kubernetes Components Installation
**Purpose**: Install kubeadm, kubelet, and kubectl.

```bash
ansible-playbook -i inventory/hosts.yml playbooks/05-kubernetes-install.yml
```

**Tasks Performed**:
- Add Kubernetes apt repository
- Install kubeadm, kubelet, kubectl
- Hold packages at current version (prevent auto-updates)
- Enable kubelet service
- Configure kubelet extra args if needed
- Verify installation versions

#### 2.6 Initialize Kubernetes Control Plane
**Purpose**: Bootstrap the Kubernetes control plane on master node(s).

```bash
ansible-playbook -i inventory/hosts.yml playbooks/06-control-plane-init.yml
```

**Tasks Performed**:
- Run `kubeadm init` on control plane node
- Configure pod network CIDR (e.g., `10.244.0.0/16`)
- Set up kubeconfig for admin user
- Generate join token for worker nodes
- Save join command for workers
- Install kubectl bash completion
- Verify control plane components are running

**Post-Initialization**:
- Control plane node will be in NotReady state until CNI is deployed (Phase 3)
- Join token saved to `/tmp/kubernetes-join-command`

#### 2.7 Join Worker Nodes
**Purpose**: Join worker nodes to the Kubernetes cluster.

```bash
ansible-playbook -i inventory/hosts.yml playbooks/07-workers-join.yml
```

**Tasks Performed**:
- Copy join command from control plane
- Execute `kubeadm join` on each worker node
- Verify nodes appear in cluster
- Label worker nodes appropriately
- Apply node taints if needed

### Complete Provisioning

Run all playbooks in sequence:
```bash
ansible-playbook -i inventory/hosts.yml playbooks/site.yml
```

### Validation

Verify the cluster from the control plane node:
```bash
# Check node status (will be NotReady until CNI deployed)
kubectl get nodes

# Verify all components
kubectl get pods -n kube-system

# Check kubelet status on all nodes
ansible all -i inventory/hosts.yml -m shell -a "systemctl status kubelet"

# Verify containerd
ansible all -i inventory/hosts.yml -m shell -a "systemctl status containerd"
```

### Troubleshooting

Common issues:
```bash
# View kubelet logs
journalctl -u kubelet -f

# Reset a node if needed
kubeadm reset
rm -rf /etc/cni/net.d
rm -rf $HOME/.kube/config

# Check containerd
crictl ps
crictl images
```

### Next Steps

After VM provisioning is complete, proceed to **Phase 3: Cluster Bootstrapping** to deploy the CNI and essential cluster services.

## Proxmox Integration Notes

### VM Creation Options

**Option 1: Manual VM Creation (Proxmox Web UI)**
1. Access Proxmox web interface at `https://<proxmox-ip>:8006`
2. Create VMs with recommended specs:
   - **Control Plane**: 4 vCPUs, 8GB RAM, 50GB disk
   - **Worker Nodes**: 8 vCPUs, 16GB RAM, 100GB+ disk
3. Install Ubuntu 22.04 LTS from ISO
4. Configure static IPs or DHCP reservations
5. Enable SSH and create initial user

**Option 2: Automated VM Creation (Terraform + Proxmox Provider)**
```hcl
# Example Terraform configuration for Proxmox VMs
resource "proxmox_vm_qemu" "k8s_master" {
  name        = "k8s-master-01"
  target_node = "proxmox-node"
  clone       = "ubuntu-22.04-template"
  cores       = 4
  memory      = 8192
  disk {
    size    = "50G"
    storage = "local-lvm"
  }
}
```

**VM Distribution**:
- VMs can be distributed across both Proxmox nodes
- Kubernetes control plane and worker VMs spread for redundancy
- Shared storage (NAS) accessible from both nodes via NFS/iSCSI

### Proxmox Cluster Architecture

This HomeLab uses a **2-node Proxmox VE cluster** for high availability and resource distribution:

**Physical Setup**:
- **Node 1 (proxmox-01)**: Physical server running Proxmox VE
- **Node 2 (proxmox-02)**: Physical server running Proxmox VE
- **Cluster Configuration**: Both nodes joined in a Proxmox cluster for centralized management

**VM Distribution**:
- VMs can be distributed across both Proxmox nodes
- Kubernetes control plane and worker VMs spread for redundancy
- Shared storage (NAS) accessible from both nodes via NFS/iSCSI

### Proxmox Best Practices

- **Cluster Setup**: Configure 2-node cluster with proper quorum device (QDevice) to avoid split-brain
- **CPU Allocation**: Use host CPU type for better performance
- **Memory**: Enable ballooning for dynamic memory allocation
- **Storage**: Use LVM-thin or ZFS for VM disks; configure shared storage for live migration
- **Networking**: Configure bridge networking (vmbr0) on both nodes for VM connectivity
- **Backups**: Set up automated VM backups via Proxmox Backup Server
- **HA**: Enable HA for critical VMs (requires proper fencing and shared storage)
- **Updates**: Keep both Proxmox nodes on the same version for cluster stability