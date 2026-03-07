# Overview
This directory contains Ansible playbooks and roles for provisioning and configuring the bare-metal Ubuntu nodes that will host the Kubernetes cluster.

## Phase 2: Bare-Metal Provisioning (Ansible)

This phase prepares the physical/virtual Ubuntu servers to run Kubernetes by installing dependencies, hardening the OS, and configuring networking.

### Prerequisites
- Ubuntu 22.04 LTS (or later) installed on all nodes
- SSH access to all nodes with sudo privileges
- Ansible >= 2.10 installed on control machine
- Inventory file configured with node IP addresses and roles
- Python 3 installed on all target nodes

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

### Deployment Steps

#### 2.1 System Updates and Hardening
**Purpose**: Update packages, configure security settings, and harden the OS.

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

#### 2.2 Host Management Tools
**Purpose**: Install Cockpit for web-based server management.

```bash
ansible-playbook -i inventory/hosts.yml playbooks/02-cockpit.yml
```

**Tasks Performed**:
- Install Cockpit and required modules
- Enable and start Cockpit service
- Configure firewall for Cockpit (port 9090)
- Set up SSL certificates (optional)
- Install additional Cockpit plugins:
  - cockpit-podman
  - cockpit-machines
  - cockpit-networkmanager

**Access**: `https://<node-ip>:9090`

#### 2.3 Networking Configuration
**Purpose**: Configure networking requirements for Kubernetes.

```bash
ansible-playbook -i inventory/hosts.yml playbooks/03-networking.yml
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

#### 2.4 Disable Swap
**Purpose**: Disable swap as required by Kubernetes.

```bash
ansible-playbook -i inventory/hosts.yml playbooks/04-disable-swap.yml
```

**Tasks Performed**:
- Turn off all swap devices (`swapoff -a`)
- Remove swap entries from `/etc/fstab`
- Verify swap is disabled
- Persist configuration across reboots

#### 2.5 Container Runtime Installation
**Purpose**: Install and configure containerd as the container runtime.

```bash
ansible-playbook -i inventory/hosts.yml playbooks/05-containerd.yml
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

#### 2.6 Kubernetes Components Installation
**Purpose**: Install kubeadm, kubelet, and kubectl.

```bash
ansible-playbook -i inventory/hosts.yml playbooks/06-kubernetes-install.yml
```

**Tasks Performed**:
- Add Kubernetes apt repository
- Install kubeadm, kubelet, kubectl
- Hold packages at current version (prevent auto-updates)
- Enable kubelet service
- Configure kubelet extra args if needed
- Verify installation versions

#### 2.7 Initialize Kubernetes Control Plane
**Purpose**: Bootstrap the Kubernetes control plane on master node(s).

```bash
ansible-playbook -i inventory/hosts.yml playbooks/07-control-plane-init.yml
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

#### 2.8 Join Worker Nodes
**Purpose**: Join worker nodes to the Kubernetes cluster.

```bash
ansible-playbook -i inventory/hosts.yml playbooks/08-workers-join.yml
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

After bare-metal provisioning is complete, proceed to **Phase 3: Cluster Bootstrapping** to deploy the CNI and essential cluster services.