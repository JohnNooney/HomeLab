# Development Environment Setup

This guide covers setting up a local Proxmox cluster on Windows for testing and development of the HomeLab Kubernetes infrastructure.

## Overview

This development environment allows you to:
- Run a multi-node Proxmox cluster locally using nested virtualization
- Test Kubernetes cluster deployments before applying to production
- Develop and validate Ansible playbooks, Terraform configurations, and Helm charts
- Simulate the full HomeLab stack on your local machine

## Prerequisites

### Hardware Requirements
- **CPU**: Intel VT-x or AMD-V capable processor with nested virtualization support
- **RAM**: Minimum 32GB (64GB+ recommended)
  - Proxmox host VMs: 12GB each × 2 = 24GB
  - Kubernetes VMs: 4GB control plane + 2GB workers × 3 = 10GB
  - Windows host overhead: ~8GB
  - **Total**: ~42GB (64GB recommended for comfortable operation)
- **Storage**: 200GB+ free disk space (SSD recommended)
- **Network**: Stable internet connection for package downloads

### Software Requirements
- **Windows 10/11 Pro** (Hyper-V support required)
- **Hyper-V** enabled
- **PowerShell 5.1+** or **PowerShell Core 7+**
- **Git** for version control
- **SSH client** (built-in Windows OpenSSH or PuTTY)
- **kubectl** for Kubernetes management
- **Helm 3+** for package management
- **Terraform 1.0+** (optional, for Phase 4)

## Phase 1: Windows Host Configuration

### 1.1 Enable Hyper-V

```powershell
# Run PowerShell as Administrator
Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V -All

# Reboot when prompted
Restart-Computer
```

### 1.2 Configure Hyper-V Networking

A PowerShell script is provided to automate network setup: `dev/helper-scripts/Setup-HyperVNetwork.ps1`

```powershell
# Run PowerShell as Administrator
cd D:\GitHub\HomeLab\dev\helper-scripts

# Setup Hyper-V network with default settings
.\Setup-HyperVNetwork.ps1

# The script will:
# - Create/verify the ProxmoxCluster switch
# - Configure gateway IP (192.168.100.1)
# - Setup NAT for internet access (192.168.100.0/24)
# - Enable IP forwarding for WSL to Hyper-V communication
```

### 1.3 Install Required Tools

```powershell
# Install Chocolatey (package manager)
Set-ExecutionPolicy Bypass -Scope Process -Force
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))

# Install kubectl
choco install kubernetes-cli -y

# Install Helm
choco install kubernetes-helm -y

# Install Terraform (optional)
choco install terraform -y

# Verify installations
kubectl version --client
helm version
terraform version
```

## Phase 2: Proxmox VE Installation

### 2.1 Download Proxmox VE ISO

```powershell
# Create directories
New-Item -Path "E:\HyperV-VMs\ISOs" -ItemType Directory -Force
New-Item -Path "E:\HyperV-VMs\VHDs" -ItemType Directory -Force

# Download Proxmox VE ISO (use browser or PowerShell)
$proxmoxUrl = "https://www.proxmox.com/en/downloads"
# Navigate to download the latest Proxmox VE ISO manually
# Save to: E:\HyperV-VMs\ISOs\proxmox-ve_9.1-1.iso
```

### 2.2 Proxmox VM Creation Script

A PowerShell script is provided to automate Proxmox VM creation: `dev/helper-scripts/Create-ProxmoxVM.ps1`

This script creates Hyper-V VMs with:
- 100GB disk (default, configurable)
- 12GB RAM (default, configurable)
- 4 vCPUs (default, configurable)
- Secure Boot disabled (required for Proxmox)

### 2.3 Create Proxmox Cluster Nodes

```powershell
# Navigate to the helper scripts directory
cd D:\GitHub\HomeLab\dev\helper-scripts

# Create Proxmox nodes with 100GB disks and 12GB RAM
.\Create-ProxmoxVM.ps1 -VMName "pve-01" -IPAddress "192.168.100.11" -MemoryGB 12 -ProcessorCount 2 -DiskSizeGB 100
.\Create-ProxmoxVM.ps1 -VMName "pve-02" -IPAddress "192.168.100.12" -MemoryGB 12 -ProcessorCount 2 -DiskSizeGB 100

# Configure nested virtualization and MAC spoofing
.\Configure-ProxmoxVMSettings.ps1 -VMNames "pve-01","pve-02"

# Start VMs
Start-VM -Name "pve-01"
Start-VM -Name "pve-02"
```

### 2.4 Install Proxmox on Each Node

For each VM:

1. **Connect to VM console**:
   ```powershell
   vmconnect.exe localhost "pve-01"
   ```

2. **Follow Proxmox installer**:
   - Select "Install Proxmox VE"
   - Accept EULA
   - Select target disk
   - Configure location and timezone
   - Set root password (e.g., `ProxmoxDev123!`)
   - Configure network:
     - Hostname: `pve-01.local` (or `pve-02.local`, `pve-03.local`)
     - IP Address: `192.168.100.11/24` (or `.12`, `.13`)
     - Gateway: `192.168.100.1`
     - DNS: `8.8.8.8`

3. **Complete installation and reboot**

4. **Access Proxmox Web UI**:
   - URL: `https://192.168.100.11:8006`
   - Username: `root`
   - Password: (as set during installation)

### 2.5 Create Proxmox Cluster

On **pve-01** (via web UI or SSH):

```bash
# SSH to pve-01
ssh root@192.168.100.11

# Verify hostname resolution (critical for clustering)
hostname -f
# Should return: pve-01.local or similar

# Check /etc/hosts has proper entries
cat /etc/hosts
# Should contain:
# 192.168.100.11 pve-01.local pve-01
# 192.168.100.12 pve-02.local pve-02

# If not, add them:
echo "192.168.100.11 pve-01.local pve-01" >> /etc/hosts
echo "192.168.100.12 pve-02.local pve-02" >> /etc/hosts

# Create cluster with explicit link
pvecm create homelab-dev --link0 192.168.100.11

# Verify cluster was created successfully
pvecm status
# Should show: Cluster information and Quorum information

# Check corosync configuration
cat /etc/pve/corosync.conf
# Should show valid cluster configuration with nodelist

# Verify corosync is running
systemctl status corosync
systemctl status pve-cluster
```

**Troubleshooting if cluster creation failed:**

```bash
# On pve-01, if cluster creation failed, clean up and retry:
systemctl stop pve-cluster
systemctl stop corosync
rm -rf /etc/pve/corosync.conf
rm -rf /etc/corosync/*
rm -rf /var/lib/corosync/*

# Restart services
systemctl start pve-cluster
systemctl start corosync

# Try creating cluster again
pvecm create homelab-dev --link0 192.168.100.11
```

On **pve-02**:

```bash
# SSH to pve-02
ssh root@192.168.100.12

# Verify hostname and /etc/hosts
hostname -f
cat /etc/hosts

# Add entries if missing
echo "192.168.100.11 pve-01.local pve-01" >> /etc/hosts
echo "192.168.100.12 pve-02.local pve-02" >> /etc/hosts

# Verify connectivity to pve-01
ping -c 3 192.168.100.11
ssh-keyscan 192.168.100.11

# Join cluster (use pve-01's IP)
pvecm add 192.168.100.11 --link0 192.168.100.12

# If prompted for password, enter root password for pve-01
```

Verify cluster:
```bash
# On any node
pvecm status
# Should show 2 nodes online

pvecm nodes
# Should list both pve-01 and pve-02

# Check cluster health
pvecm expected 2
```

### 2.6 Configure Proxmox Storage

On each node, configure local storage:

```bash
# Create directory for VM images
mkdir -p /var/lib/vz/images

# Verify storage
pvesm status
```

## Phase 3: Kubernetes VM Provisioning

### 3.1 Generate SSH Key Pair

Before creating VMs, generate an SSH key pair on your Windows host for passwordless authentication:

**On Windows (PowerShell)**:
```powershell
# Generate SSH key pair
ssh-keygen -t rsa -b 4096 -C "homelab-dev" -f "$env:USERPROFILE\.ssh\homelab-dev"

# Display public key (you'll need this for the VM creation script)
Get-Content "$env:USERPROFILE\.ssh\homelab-dev.pub"

# Run PowerShell as Administrator, then:
Get-Service ssh-agent | Set-Service -StartupType Automatic
Start-Service ssh-agent

# Now add your key
ssh-add $env:USERPROFILE\.ssh\homelab-dev

# Verify it's loaded
ssh-add -l
```

**Copy the public key output** - it will look like:
```
ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAACAQDExampleKey... homelab-dev
```


You'll use this public key in the `create-k8s-cluster.sh` script in step 3.3.

### 3.2 Download Ubuntu Cloud Image

On **pve-01**:

```bash
# Download Ubuntu 22.04 cloud image
cd /var/lib/vz/template/iso
wget https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.img

# Verify download
ls -lh jammy-server-cloudimg-amd64.img
```

### 3.3 Create VM Templates on All Nodes

**IMPORTANT**: Since Proxmox uses local storage (`local-lvm`), templates are NOT shared across nodes. Each node needs its own template with a **unique ID**.

#### Option A: Automated Template Creation (Recommended)

Use the automated script to create templates on all nodes at once:

**Transfer and run the automated script**:
```powershell
# From your Windows host
scp dev/helper-scripts/create-templates-all-nodes.sh root@192.168.100.11:/root/
```

```bash
# SSH to any Proxmox node
ssh root@192.168.100.11

# Make executable and run
chmod +x /root/create-templates-all-nodes.sh
/root/create-templates-all-nodes.sh
```

**What the automated script does**:
- Creates templates on all configured Proxmox nodes
- Assigns unique template IDs per node (pve: 9000, pve2: 9001, etc.)
- Downloads Ubuntu cloud image if not present
- Skips nodes where templates already exist
- Provides a summary of success/failure for each node

#### Option B: Manual Template Creation Per Node

If you prefer manual control, create templates individually on each node:

**On pve-01 (Template ID 9000)**:
```bash
scp dev/helper-scripts/create-k8s-template.sh root@192.168.100.11:/root/
ssh root@192.168.100.11
chmod +x /root/create-k8s-template.sh
# Edit TEMPLATE_ID=9000 in the script
./create-k8s-template.sh
```

**On pve-02 (Template ID 9001)**:
```bash
scp dev/helper-scripts/create-k8s-template.sh root@192.168.100.12:/root/
ssh root@192.168.100.12
chmod +x /root/create-k8s-template.sh
# Edit TEMPLATE_ID=9001 in the script
./create-k8s-template.sh
```

**Template ID Mapping**:
- `pve`: Template ID 9000
- `pve2`: Template ID 9001
- `pve3`: Template ID 9002 (if applicable)

### 3.4 Create Kubernetes VMs

**IMPORTANT**: Before using this script, you must edit `dev/helper-scripts/create-k8s-cluster.sh` and replace the `SSH_KEY` variable with your actual public key from step 3.1.

**Edit the script**:
```powershell
# Open the script in your editor
notepad dev\helper-scripts\create-k8s-cluster.sh

# Replace this line:
# SSH_KEY="ssh-rsa AAAAB3... your-key-here"
# With your actual public key from step 3.1
```

**Transfer script to Proxmox**:
```powershell
# From your Windows host
scp dev/helper-scripts/create-k8s-cluster.sh root@192.168.100.11:/root/
```

**Run the script on pve-01**:
```bash
# SSH to pve-01
ssh root@192.168.100.11

# Make executable and run
chmod +x /root/create-k8s-cluster.sh
/root/create-k8s-cluster.sh
```

**What the script does**:
- Clones 4 VMs from templates distributed across Proxmox nodes
- Automatically uses the correct template ID for each target node (pve: 9000, pve2: 9001)
- Assigns static IP addresses to each VM
- Configures cloud-init with your SSH key for passwordless access
- Resizes disks to provide additional storage
- Starts all VMs automatically

**VM Distribution**:
The script distributes VMs across your Proxmox cluster. Update the node assignments in the script as needed:
```bash
create_vm 101 "k8s-control-01" "192.168.100.21" "pve-01"   # Control plane on pve
create_vm 201 "k8s-worker-01" "192.168.100.31" "pve-01"   # Worker 1 on pve
create_vm 202 "k8s-worker-02" "192.168.100.32" "pve-02"  # Worker 2 on pve2
create_vm 203 "k8s-worker-03" "192.168.100.33" "pve-02"  # Worker 3 on pve2
```

**Wait 2-3 minutes** for cloud-init to complete before attempting SSH access.

### 3.5 Verify VM Connectivity

From your Windows host:

```powershell
# Test SSH connectivity
ssh ubuntu@192.168.100.21  # Control plane
ssh ubuntu@192.168.100.31  # Worker 1
ssh ubuntu@192.168.100.32  # Worker 2
ssh ubuntu@192.168.100.33  # Worker 3
```

## Phase 3.6: Setup Ansible on Windows using WSL

Before running Ansible playbooks, you need to set up Ansible on your Windows machine using Windows Subsystem for Linux (WSL).

### 3.6.1 Install WSL

**Enable WSL on Windows**:
```powershell
# Run PowerShell as Administrator
wsl --install

# Or if WSL is already installed, install Ubuntu
wsl --install -d Ubuntu

# Reboot when prompted
Restart-Computer
```

**Verify WSL installation**:
```powershell
# Check WSL version
wsl --list --verbose

# Should show Ubuntu running WSL 2
```

**Enable IP forwarding for WSL to Hyper-V communication**:
```powershell
# Run PowerShell as Administrator
# Enable forwarding on both virtual network interfaces
Set-NetIPInterface -InterfaceAlias "vEthernet (ProxmoxCluster)" -Forwarding Enabled
Set-NetIPInterface -InterfaceAlias "vEthernet (WSL (Hyper-V firewall))" -Forwarding Enabled
```

> **Note**: This step is required to allow WSL2 to communicate with VMs running on Hyper-V's Default Switch network. Without IP forwarding enabled, SSH and Ansible connections from WSL to your Kubernetes VMs will fail.

### 3.6.2 Configure WSL Ubuntu

**Launch WSL Ubuntu**:
```powershell
# Start WSL
wsl
```

**Initial setup** (first time only):
```bash
# You'll be prompted to create a username and password
# Example: username=homelab, password=<your-secure-password>

# Update package lists
sudo apt update && sudo apt upgrade -y
```

### 3.6.3 Install Ansible in WSL

```bash
# Install software-properties-common for add-apt-repository
sudo apt install software-properties-common -y

# Add Ansible PPA repository
sudo add-apt-repository --yes --update ppa:ansible/ansible

# Install Ansible
sudo apt install ansible -y

# Verify Ansible installation
ansible --version

# Install additional Python dependencies
sudo apt install python3-pip -y
sudo apt install python3-jmespath
```

### 3.6.4 Configure SSH Access from WSL

**Copy SSH keys from Windows to WSL**:
```bash
# Create .ssh directory in WSL
mkdir -p ~/.ssh
chmod 700 ~/.ssh

# Copy SSH key from Windows to WSL
# Replace <WINDOWS_USERNAME> with your Windows username
cp /mnt/c/Users/<WINDOWS_USERNAME>/.ssh/homelab-dev ~/.ssh/
cp /mnt/c/Users/<WINDOWS_USERNAME>/.ssh/homelab-dev.pub ~/.ssh/

# Set correct permissions
chmod 600 ~/.ssh/homelab-dev
chmod 644 ~/.ssh/homelab-dev.pub

# Add key to SSH agent
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/homelab-dev

# Verify key is loaded
ssh-add -l
```

**Test SSH connectivity to Kubernetes VMs**:
```bash
# Test connection to control plane
ssh -i ~/.ssh/homelab-dev ubuntu@192.168.100.21

# Test connection to workers
ssh -i ~/.ssh/homelab-dev ubuntu@192.168.100.31
ssh -i ~/.ssh/homelab-dev ubuntu@192.168.100.32
ssh -i ~/.ssh/homelab-dev ubuntu@192.168.100.33

# Exit each SSH session after testing
exit
```

### 3.6.5 Access HomeLab Repository in WSL

**Navigate to your repository**:
```bash
# Windows drives are mounted at /mnt/<drive-letter>
cd /mnt/d/GitHub/HomeLab

# Verify you're in the correct directory
pwd
ls -la

# Navigate to ansible directory
cd ansible
```

**Alternative: Clone repository in WSL** (optional):
```bash
# If you prefer to work entirely in WSL
cd ~
git clone https://github.com/<your-username>/HomeLab.git
cd HomeLab/ansible
```

### 3.6.6 Configure Ansible Settings

**Create ansible.cfg** (optional but recommended):
```bash
# Create ansible.cfg in the ansible directory
cat > ansible.cfg << 'EOF'
[defaults]
inventory = inventory/dev.yml
host_key_checking = False
private_key_file = ~/.ssh/homelab-dev
remote_user = ubuntu
retry_files_enabled = False
stdout_callback = yaml

[privilege_escalation]
become = True
become_method = sudo
become_user = root
become_ask_pass = False

[ssh_connection]
ssh_args = -o ControlMaster=auto -o ControlPersist=60s -o StrictHostKeyChecking=no
pipelining = True
EOF
```

### 3.6.7 Verify Ansible Setup

**Test Ansible connectivity**:
```bash
# Navigate to ansible directory
cd /mnt/d/GitHub/HomeLab/ansible

# Test ping to all hosts
ansible all -i inventory/dev.yml -m ping

# Expected output: SUCCESS for all hosts
# k8s-control-01 | SUCCESS => { "changed": false, "ping": "pong" }
# k8s-worker-01 | SUCCESS => { "changed": false, "ping": "pong" }
# k8s-worker-02 | SUCCESS => { "changed": false, "ping": "pong" }
# k8s-worker-03 | SUCCESS => { "changed": false, "ping": "pong" }
```

**Test ad-hoc commands**:
```bash
# Check uptime on all nodes
ansible all -i inventory/dev.yml -m command -a "uptime"

# Check disk space
ansible all -i inventory/dev.yml -m command -a "df -h"

# Verify Ubuntu version
ansible all -i inventory/dev.yml -m command -a "lsb_release -a"
```

### 3.6.8 WSL Tips and Best Practices

**Accessing WSL from Windows**:
- WSL filesystem: `\\wsl$\Ubuntu-22.04\home\<username>`
- Windows filesystem from WSL: `/mnt/c/`, `/mnt/d/`, etc.

**Performance considerations**:
- Work on files in WSL filesystem (`~/`) for better performance
- Or work directly from Windows filesystem (`/mnt/d/`) for easier access from Windows tools

**Useful WSL commands**:
```powershell
# From PowerShell/CMD:
# Start WSL
wsl

# Run a command in WSL without entering shell
wsl ls -la

# Shutdown WSL
wsl --shutdown

# List WSL distributions
wsl --list --verbose

# Set default WSL distribution
wsl --set-default Ubuntu-22.04
```

**WSL resource management**:
Create `.wslconfig` in `C:\Users\<USERNAME>\`:
```ini
[wsl2]
memory=8GB
processors=4
swap=2GB
```

## Phase 4: Kubernetes Cluster Setup

### 4.1 Verify Ansible Inventory

Verify the Ansible inventory has the expected configurations at `ansible/inventory/dev.yml`:

```yaml
all:
  children:
    control_plane:
      hosts:
        k8s-control-01:
          ansible_host: 192.168.100.21
    workers:
      hosts:
        k8s-worker-01:
          ansible_host: 192.168.100.31
        k8s-worker-02:
          ansible_host: 192.168.100.32
        k8s-worker-03:
          ansible_host: 192.168.100.33
    k8s_cluster:
      children:
        - control_plane
        - workers
  vars:
    ansible_user: ubuntu
    ansible_become: yes
    ansible_python_interpreter: /usr/bin/python3
    ansible_ssh_common_args: '-o StrictHostKeyChecking=no'
```

**Note**: If your VM IP addresses differ, update the `ansible_host` values in `ansible/inventory/dev.yml` accordingly.

### 4.2 Run Ansible Playbooks

Run the Ansible playbooks from WSL to install and configure Kubernetes:

```bash
# Navigate to ansible directory in WSL
cd /mnt/d/GitHub/HomeLab/ansible

# Option 1: Run the complete installation using site.yml (recommended)
ansible-playbook -i inventory/dev.yml playbooks/site.yml

# Option 2: Run the all-in-one k8s-install.yml playbook
ansible-playbook -i inventory/dev.yml playbooks/k8s-install.yml

# Option 3: Run individual playbooks step-by-step
ansible-playbook -i inventory/dev.yml playbooks/01-system-update.yml
ansible-playbook -i inventory/dev.yml playbooks/02-networking.yml
ansible-playbook -i inventory/dev.yml playbooks/03-disable-swap.yml
ansible-playbook -i inventory/dev.yml playbooks/04-containerd.yml
ansible-playbook -i inventory/dev.yml playbooks/05-kubernetes-install.yml
ansible-playbook -i inventory/dev.yml playbooks/06-control-plane-init.yml
ansible-playbook -i inventory/dev.yml playbooks/07-workers-join.yml
```

**Playbook descriptions**:
- **site.yml**: Runs all playbooks in sequence (complete end-to-end installation)
- **k8s-install.yml**: All-in-one playbook combining all installation steps
- **01-system-update.yml**: System updates, hardening, and firewall configuration
- **02-networking.yml**: Kernel modules and networking configuration for Kubernetes
- **03-disable-swap.yml**: Disable swap (required by Kubernetes)
- **04-containerd.yml**: Install and configure containerd runtime
- **05-kubernetes-install.yml**: Install kubeadm, kubelet, and kubectl
- **06-control-plane-init.yml**: Initialize Kubernetes control plane
- **07-workers-join.yml**: Join worker nodes to the cluster

### 4.3 Verify Cluster Installation

```bash
# SSH to control plane from WSL
ssh ubuntu@192.168.100.21

# Check cluster nodes
kubectl get nodes

# Check system pods
kubectl get pods -n kube-system

# Exit SSH session
exit
```

## Phase 5: Kubernetes Cluster Bootstrapping

After the Kubernetes cluster is initialized via Ansible, deploy essential cluster services based on `kubernetes/README.md`.

### 5.1 Configure kubectl Access

From your Windows host:

```powershell
# Create .kube directory
New-Item -Path "$env:USERPROFILE\.kube" -ItemType Directory -Force

# Copy kubeconfig from control plane
scp ubuntu@192.168.100.21:~/.kube/config "$env:USERPROFILE\.kube\config"

# Verify access
kubectl get nodes
```

### 5.2 Deploy Container Network Interface (CNI)

**Option A: Calico**
```powershell
# Download Calico manifest
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/projectcalico/calico/v3.26.0/manifests/calico.yaml" -OutFile "calico.yaml"

# Apply Calico
kubectl apply -f calico.yaml

# Verify deployment
kubectl get pods -n kube-system -l k8s-app=calico-node
kubectl get pods -n kube-system -l k8s-app=calico-kube-controllers
```

**Option B: Cilium**
```powershell
# Add Cilium Helm repository
helm repo add cilium https://helm.cilium.io/
helm repo update

# Install Cilium
helm install cilium cilium/cilium `
  --namespace kube-system `
  --set operator.replicas=1

# Verify deployment
kubectl get pods -n kube-system -l k8s-app=cilium
```

**Validation**:
```powershell
# Nodes should now be Ready
kubectl get nodes

# All kube-system pods should be Running
kubectl get pods -n kube-system

# Test pod networking
kubectl run test-pod --image=nginx --rm -it -- /bin/bash
```

### 5.3 Deploy Ingress Controller

```powershell
# Add ingress-nginx Helm repository
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo update

# Install ingress-nginx
helm install ingress-nginx ingress-nginx/ingress-nginx `
  --namespace ingress-nginx `
  --create-namespace `
  --set controller.service.type=NodePort `
  --set controller.service.nodePorts.http=30080 `
  --set controller.service.nodePorts.https=30443

# Verify deployment
kubectl get pods -n ingress-nginx
kubectl get svc -n ingress-nginx
```

**Access Applications**:
- HTTP: `http://192.168.100.21:30080`
- HTTPS: `https://192.168.100.21:30443`

### 5.4 Deploy Storage Provisioner (Local Path)

For development, use local-path-provisioner:

```powershell
# Install local-path-provisioner
kubectl apply -f https://raw.githubusercontent.com/rancher/local-path-provisioner/v0.0.24/deploy/local-path-storage.yaml

# Set as default storage class
kubectl patch storageclass local-path -p '{\"metadata\": {\"annotations\":{\"storageclass.kubernetes.io/is-default-class\":\"true\"}}}'

# Verify
kubectl get storageclass
```

### 5.5 Validation Checklist

```powershell
# All nodes are Ready
kubectl get nodes

# All system pods are Running
kubectl get pods --all-namespaces

# DNS resolution works
kubectl run -it --rm debug --image=busybox --restart=Never -- nslookup kubernetes.default

# Ingress controller is running
kubectl get pods -n ingress-nginx

# Storage class is available
kubectl get storageclass
```

## Phase 6: Application Deployment with Helm

Deploy applications to your development cluster using Helm charts based on `helm/README.md`.

**Development-Optimized Values**: Use the dev-specific values files in `helm/values/dev/` which are optimized for low-resource environments:
- Reduced CPU/memory requests and limits (50-80% smaller)
- Smaller persistent volume sizes
- NodePort services for easy access without LoadBalancer
- Shorter data retention periods
- Total resource footprint: ~2.5 vCPU, ~6GB RAM, ~60GB storage

See `helm/README.md` for detailed resource comparisons and NodePort assignments.

### 6.1 Deploy Observability Stack

**Create namespace**:
```powershell
kubectl create namespace monitoring
```

**Deploy kube-prometheus-stack**:
```powershell
# Add Prometheus Helm repository
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

# Install kube-prometheus-stack using dev values
helm install kube-prometheus-stack prometheus-community/kube-prometheus-stack `
  --namespace monitoring `
  --values helm/values/dev/prometheus-stack.yaml `
  --set grafana.adminPassword=admin `
  --set grafana.service.type=NodePort `
  --set grafana.service.nodePort=30300 `
  --set prometheus.service.type=NodePort `
  --set prometheus.service.nodePort=30900

# Verify deployment
kubectl get pods -n monitoring
```

**Access Grafana**:
- URL: `http://192.168.100.21:30300`
- Username: `admin`
- Password: `admin`

### 6.2 Deploy Media Stack Applications

**Create namespace**:
```powershell
kubectl create namespace media
```

**Add required Helm repositories**:
```powershell
# Add k8s-home-lab Helm repository (for media apps)
helm repo add k8s-home-lab https://k8s-home-lab.github.io/helm-charts/
helm repo update
```

**Deploy media applications using dev values**:

All media applications use optimized dev values from `helm/values/dev/` with NodePort services pre-configured.

**Plex** (Media Server):
```powershell
helm install plex k8s-home-lab/plex `
  --namespace media `
  --values helm/values/dev/plex.yaml

# NOTE: Plex only binds to localhost until initial setup is complete
# For first-time setup, use port-forward:
kubectl port-forward -n media deployment/plex 32400:32400
# Then access: http://localhost:32400/web
# Complete the setup wizard, then access via NodePort: http://192.168.100.21:32400/web
# Address may be one of the other workers, so check the other Node IPs if above isn't accessible
```

**Sonarr** (TV management):
```powershell
helm install sonarr k8s-home-lab/sonarr `
  --namespace media `
  --values helm/values/dev/sonarr.yaml

# Access: http://192.168.100.21:30989
```

**Radarr** (Movie management):
```powershell
helm install radarr k8s-home-lab/radarr `
  --namespace media `
  --values helm/values/dev/radarr.yaml

# Access: http://192.168.100.21:30787
```

**Prowlarr** (Indexer management):
```powershell
helm install prowlarr k8s-home-lab/prowlarr `
  --namespace media `
  --values helm/values/dev/prowlarr.yaml

# Access: http://192.168.100.21:30906
```

**Lidarr** (Music management):
```powershell
helm install lidarr k8s-home-lab/lidarr `
  --namespace media `
  --values helm/values/dev/lidarr.yaml

# Access: http://192.168.100.21:30868
```

**Bazarr** (Subtitle management):
```powershell
helm install bazarr k8s-home-lab/bazarr `
  --namespace media `
  --values helm/values/dev/bazarr.yaml

# Access: http://192.168.100.21:30676
```

**Transmission** (Torrent client):
```powershell
# Add lexfrei helm repository (OCI-based)
helm install transmission `
  oci://ghcr.io/lexfrei/charts/transmission `
  --namespace media `
  --values helm/values/dev/transmission.yaml

# Access: http://192.168.100.21:30091
# Address may be one of the other workers, so check the other Node IPs if above isn't accessible
```

### 6.3 Verify Media Stack Deployment

```powershell
# Check all pods in media namespace
kubectl get pods -n media

# Check services and NodePorts
kubectl get svc -n media
```

### 6.4 Deploy Services Stack

**Create namespace**:
```powershell
kubectl create namespace services
```

**Home Assistant**:
```powershell
helm install home-assistant k8s-home-lab/home-assistant `
  --namespace services `
  --values helm/values/dev/home-assistant.yaml

# Access: http://192.168.100.21:30812
```

**Immich** (Photo management with PostgreSQL):
```powershell
# Deploy PostgreSQL first
helm repo add bitnami https://charts.bitnami.com/bitnami
helm install postgresql bitnami/postgresql `
  --namespace services `
  --set auth.database=immich `
  --set auth.password=immichdev123 `
  --set primary.resources.requests.cpu=100m `
  --set primary.resources.requests.memory=256Mi `
  --set primary.resources.limits.cpu=500m `
  --set primary.resources.limits.memory=512Mi `
  --set primary.persistence.size=5Gi

# Deploy Immich using dev values
helm repo add immich https://immich-app.github.io/immich-charts
helm install immich immich/immich `
  --namespace services `
  --values helm/values/dev/immich.yaml

# Access: http://192.168.100.21:30283 (check actual NodePort with kubectl get svc -n services)
```

### 6.5 Using Terraform for Application Deployment (Optional)

For a production-like workflow using Terraform as described in `helm/README.md`:

**Update Terraform to use dev values files**:
```hcl
# In terraform/homelab/media.tf, reference dev values:
resource "helm_release" "plex" {
  name       = "plex"
  repository = "https://k8s-home-lab.github.io/helm-charts/"
  chart      = "plex"
  namespace  = kubernetes_namespace.media.metadata[0].name

  values = [
    file("${path.module}/../../helm/values/dev/plex.yaml")
  ]
}
```

**Create dev-specific Terraform configuration**:
```powershell
# Navigate to terraform directory
cd terraform/homelab

# Create dev.tfvars
@"
domain = "nooney.dev"
grafana_admin_password = "admin"
environment = "development"
"@ | Out-File -FilePath dev.tfvars

# Initialize Terraform
terraform init

# Plan deployment
terraform plan -var-file="dev.tfvars"

# Apply deployment
terraform apply -var-file="dev.tfvars"
```

### 6.6 Verify All Deployments

```powershell
# Check all namespaces
kubectl get namespaces

# Check pods in each namespace
kubectl get pods -n monitoring
kubectl get pods -n media
kubectl get pods -n services

# Check Helm releases
helm list --all-namespaces

# Check ingress resources (if configured)
kubectl get ingress --all-namespaces
```

## Maintenance and Management

### Snapshot Management

```powershell
# Create snapshot of Proxmox VM
ssh root@192.168.100.11
qm snapshot 101 pre-upgrade --description "Before Kubernetes upgrade"

# List snapshots
qm listsnapshot 101

# Rollback to snapshot
qm rollback 101 pre-upgrade
```

### Cluster Backup

```powershell
# Backup Kubernetes cluster state
kubectl get all --all-namespaces -o yaml > cluster-backup.yaml

# Backup Helm releases
helm list --all-namespaces -o yaml > helm-releases.yaml

# Backup etcd (on control plane)
ssh ubuntu@192.168.100.21
sudo ETCDCTL_API=3 etcdctl snapshot save /tmp/etcd-snapshot.db `
  --endpoints=https://127.0.0.1:2379 `
  --cacert=/etc/kubernetes/pki/etcd/ca.crt `
  --cert=/etc/kubernetes/pki/etcd/server.crt `
  --key=/etc/kubernetes/pki/etcd/server.key
```

### Cluster Cleanup

```powershell
# Delete all Helm releases
helm list --all-namespaces --short | ForEach-Object { helm uninstall $_ }

# Reset Kubernetes cluster (on each node)
ssh ubuntu@192.168.100.21
sudo kubeadm reset -f

# Delete Proxmox VMs
ssh root@192.168.100.11
qm stop 101 && qm destroy 101
qm stop 201 && qm destroy 201
qm stop 202 && qm destroy 202
qm stop 203 && qm destroy 203
```

## Troubleshooting

### Hyper-V Issues

**VM won't start**:
```powershell
# Check VM status
Get-VM -Name "pve-01"

# Check event logs
Get-WinEvent -LogName "Microsoft-Windows-Hyper-V-VMMS-Admin" -MaxEvents 20
```

**Nested virtualization not working**:
```powershell
# Verify nested virtualization is enabled
Get-VMProcessor -VMName "pve-01" | Select-Object ExposeVirtualizationExtensions

# Enable if disabled
Set-VMProcessor -VMName "pve-01" -ExposeVirtualizationExtensions $true
```

### Proxmox Issues

**Cluster communication problems**:
```bash
# Check cluster status
pvecm status

# Check corosync
systemctl status corosync

# View corosync logs
journalctl -u corosync -f
```

**Storage issues**:
```bash
# Check storage status
pvesm status

# Verify disk space
df -h
```

### Kubernetes Issues

**Nodes not ready**:
```powershell
kubectl get nodes
kubectl describe node k8s-worker-01
```

**Pods not starting**:
```powershell
kubectl get pods --all-namespaces
kubectl describe pod <pod-name> -n <namespace>
kubectl logs <pod-name> -n <namespace>
```

**Network connectivity issues**:
```powershell
# Test pod-to-pod networking
kubectl run test-1 --image=busybox --rm -it -- sh
kubectl run test-2 --image=busybox --rm -it -- sh
# From test-1, ping test-2's IP
```

## Resource Optimization

### Reduce Resource Usage

For limited hardware, adjust VM resources:

```bash
# On Proxmox host
qm set 101 --memory 2048 --cores 1  # Control plane
qm set 201 --memory 2048 --cores 1  # Worker 1
qm set 202 --memory 2048 --cores 1  # Worker 2
```

### Single-Node Cluster

For minimal setup, create a single-node cluster:

```bash
# Create only one VM
create_vm 101 "k8s-control-01" "192.168.100.21"

# Allow control plane to run workloads
kubectl taint nodes k8s-control-01 node-role.kubernetes.io/control-plane:NoSchedule-
```

## Next Steps

1. **Explore Ansible playbooks** in `ansible/README.md` for automated provisioning
2. **Review Kubernetes manifests** in `kubernetes/README.md` for cluster bootstrapping details
3. **Deploy applications** using Helm charts from `helm/README.md`
4. **Test Terraform workflows** in `terraform/` for infrastructure-as-code
5. **Experiment with monitoring** using Prometheus and Grafana
6. **Practice disaster recovery** with backups and restores

## Additional Resources

- [Proxmox VE Documentation](https://pve.proxmox.com/pve-docs/)
- [Kubernetes Documentation](https://kubernetes.io/docs/)
- [Helm Documentation](https://helm.sh/docs/)
- [Hyper-V Documentation](https://docs.microsoft.com/en-us/virtualization/hyper-v-on-windows/)
