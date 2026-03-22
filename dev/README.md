# Development Environment Setup

This guide covers setting up a local Proxmox cluster on Windows for testing and development of your HomeLab Kubernetes infrastructure.

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
  - Proxmox host VMs: 4GB each × 3 = 12GB
  - Kubernetes VMs: 4GB each × 3 = 12GB
  - Windows host overhead: ~8GB
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

### 1.2 Enable Nested Virtualization

After reboot, configure Hyper-V for nested virtualization:

```powershell
# Set processor compatibility mode for VM migration
Set-VMProcessor -VMName <VM-NAME> -ExposeVirtualizationExtensions $true

# Enable MAC address spoofing (required for nested networking)
Get-VMNetworkAdapter -VMName <VM-NAME> | Set-VMNetworkAdapter -MacAddressSpoofing On
```

### 1.3 Create Virtual Network Switch

```powershell
# Create an internal virtual switch for the cluster
New-VMSwitch -Name "ProxmoxCluster" -SwitchType Internal

# Configure NAT for internet access
New-NetIPAddress -IPAddress 192.168.100.1 -PrefixLength 24 -InterfaceAlias "vEthernet (ProxmoxCluster)"
New-NetNat -Name "ProxmoxClusterNAT" -InternalIPInterfaceAddressPrefix 192.168.100.0/24
```

### 1.4 Install Required Tools

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
# Create download directory
New-Item -Path "C:\ProxmoxLab" -ItemType Directory -Force

# Download Proxmox VE ISO (use browser or PowerShell)
$proxmoxUrl = "https://www.proxmox.com/en/downloads"
# Navigate to download the latest Proxmox VE ISO manually
# Save to: C:\ProxmoxLab\proxmox-ve_9.x.iso
```

### 2.2 Create Proxmox VM Template Script

Save this as `C:\ProxmoxLab\Create-ProxmoxVM.ps1`:

```powershell
param(
    [Parameter(Mandatory=$true)]
    [string]$VMName,
    
    [Parameter(Mandatory=$true)]
    [string]$IPAddress,
    
    [int]$MemoryGB = 4,
    [int]$ProcessorCount = 2,
    [int]$DiskSizeGB = 100
)

# Create VM
New-VM -Name $VMName -MemoryStartupBytes ($MemoryGB * 1GB) -Generation 2 -SwitchName "ProxmoxCluster"

# Configure VM
Set-VM -Name $VMName -ProcessorCount $ProcessorCount -AutomaticCheckpointsEnabled $false
Set-VMMemory -VMName $VMName -DynamicMemoryEnabled $false

# Create and attach virtual hard disk
$vhdPath = "C:\ProxmoxLab\VHDs\$VMName.vhdx"
New-VHD -Path $vhdPath -SizeBytes ($DiskSizeGB * 1GB) -Dynamic
Add-VMHardDiskDrive -VMName $VMName -Path $vhdPath

# Attach Proxmox ISO
Add-VMDvdDrive -VMName $VMName -Path "C:\ProxmoxLab\proxmox-ve_8.x.iso"

# Enable nested virtualization
Set-VMProcessor -VMName $VMName -ExposeVirtualizationExtensions $true

# Enable MAC spoofing
Get-VMNetworkAdapter -VMName $VMName | Set-VMNetworkAdapter -MacAddressSpoofing On

# Disable Secure Boot (Proxmox uses GRUB)
Set-VMFirmware -VMName $VMName -EnableSecureBoot Off

Write-Host "VM $VMName created successfully"
Write-Host "Assigned IP: $IPAddress"
Write-Host "Start the VM and complete Proxmox installation manually"
```

### 2.3 Create Proxmox Cluster Nodes

```powershell
# Create three Proxmox nodes
.\Create-ProxmoxVM.ps1 -VMName "pve-01" -IPAddress "192.168.100.11" -MemoryGB 4 -ProcessorCount 2
.\Create-ProxmoxVM.ps1 -VMName "pve-02" -IPAddress "192.168.100.12" -MemoryGB 4 -ProcessorCount 2
.\Create-ProxmoxVM.ps1 -VMName "pve-03" -IPAddress "192.168.100.13" -MemoryGB 4 -ProcessorCount 2

# Start VMs
Start-VM -Name "pve-01"
Start-VM -Name "pve-02"
Start-VM -Name "pve-03"
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

# Create cluster
pvecm create homelab-dev

# Check cluster status
pvecm status
```

On **pve-02** and **pve-03**:

```bash
# SSH to pve-02
ssh root@192.168.100.12

# Join cluster (use pve-01's IP)
pvecm add 192.168.100.11

# Repeat for pve-03
ssh root@192.168.100.13
pvecm add 192.168.100.11
```

Verify cluster:
```bash
# On any node
pvecm status
pvecm nodes
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

### 3.3 Create VM Template Script

Copy the template creation script to **pve-01**. The script is available at `dev/helper-scripts/create-k8s-template.sh` in this repository.

**Transfer script to Proxmox**:
```powershell
# From your Windows host
scp dev/helper-scripts/create-k8s-template.sh root@192.168.100.11:/root/
```

**Run the script on pve-01**:
```bash
# SSH to pve-01
ssh root@192.168.100.11

# Make executable and run
chmod +x /root/create-k8s-template.sh
/root/create-k8s-template.sh
```

**What the script does**:
- Creates a VM with ID 9000 named "ubuntu-k8s-template"
- Imports the Ubuntu cloud image as a disk
- Configures cloud-init support
- Sets up serial console and QEMU guest agent
- Converts the VM to a reusable template

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
- Clones 4 VMs from the template (1 control plane + 3 workers)
- Assigns static IP addresses (192.168.100.21, .31, .32, .33)
- Configures cloud-init with your SSH key for passwordless access
- Resizes disks to provide additional storage
- Starts all VMs automatically

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

## Phase 4: Kubernetes Cluster Setup

### 4.1 Prepare Ansible Inventory

On your Windows host, create `inventory/dev.ini`:

```ini
[control_plane]
k8s-control-01 ansible_host=192.168.100.21 ansible_user=ubuntu

[workers]
k8s-worker-01 ansible_host=192.168.100.31 ansible_user=ubuntu
k8s-worker-02 ansible_host=192.168.100.32 ansible_user=ubuntu
k8s-worker-03 ansible_host=192.168.100.33 ansible_user=ubuntu

[k8s_cluster:children]
control_plane
workers

[k8s_cluster:vars]
ansible_python_interpreter=/usr/bin/python3
ansible_ssh_common_args='-o StrictHostKeyChecking=no'
```

### 4.2 Run Ansible Playbooks

Refer to the Ansible playbooks in the `ansible/` directory. Run from Windows using WSL or a Linux VM:

```bash
# Install Ansible (if using WSL)
sudo apt update
sudo apt install ansible -y

# Navigate to ansible directory
cd /mnt/d/GitHub/HomeLab/ansible

# Run Kubernetes installation playbook
ansible-playbook -i inventory/dev.ini playbooks/k8s-install.yml

# Verify cluster
ssh ubuntu@192.168.100.21
kubectl get nodes
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

# Install kube-prometheus-stack
helm install kube-prometheus-stack prometheus-community/kube-prometheus-stack `
  --namespace monitoring `
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

Based on the Helm values files in `helm/values/`, deploy media applications:

**Create namespace**:
```powershell
kubectl create namespace media
```

**Example: Deploy Plex**:
```powershell
# Add bjw-s Helm repository
helm repo add bjw-s https://bjw-s.github.io/helm-charts
helm repo update

# Create custom values file for dev environment
# Adjust helm/values/plex.yaml for NodePort and smaller resources

# Install Plex
helm install plex bjw-s/app-template `
  --namespace media `
  --values helm/values/plex.yaml `
  --set service.main.type=NodePort `
  --set service.main.ports.http.nodePort=32400

# Verify deployment
kubectl get pods -n media
```

**Access Plex**:
- URL: `http://192.168.100.21:32400/web`

### 6.3 Deploy Additional Media Applications

Following the pattern from `helm/README.md`, deploy:

**Sonarr** (TV management):
```powershell
helm install sonarr bjw-s/app-template `
  --namespace media `
  --values helm/values/sonarr.yaml `
  --set service.main.type=NodePort `
  --set service.main.ports.http.nodePort=30989
```

**Radarr** (Movie management):
```powershell
helm install radarr bjw-s/app-template `
  --namespace media `
  --values helm/values/radarr.yaml `
  --set service.main.type=NodePort `
  --set service.main.ports.http.nodePort=30787
```

**Prowlarr** (Indexer management):
```powershell
helm install prowlarr bjw-s/app-template `
  --namespace media `
  --values helm/values/prowlarr.yaml `
  --set service.main.type=NodePort `
  --set service.main.ports.http.nodePort=30906
```

**Transmission** (Torrent client):
```powershell
helm install transmission bjw-s/app-template `
  --namespace media `
  --values helm/values/transmission.yaml `
  --set service.main.type=NodePort `
  --set service.main.ports.http.nodePort=30091
```

### 6.4 Deploy Services Stack

**Create namespace**:
```powershell
kubectl create namespace services
```

**Home Assistant**:
```powershell
helm install home-assistant bjw-s/app-template `
  --namespace services `
  --values helm/values/home-assistant.yaml `
  --set service.main.type=NodePort `
  --set service.main.ports.http.nodePort=30812
```

**Immich** (with PostgreSQL):
```powershell
# Deploy PostgreSQL first
helm repo add bitnami https://charts.bitnami.com/bitnami
helm install postgresql bitnami/postgresql `
  --namespace services `
  --set auth.database=immich `
  --set auth.password=immichdev123

# Deploy Immich
helm repo add immich https://immich-app.github.io/immich-charts
helm install immich immich/immich `
  --namespace services `
  --values helm/values/immich.yaml `
  --set service.main.type=NodePort `
  --set service.main.ports.http.nodePort=30283
```

### 6.5 Using Terraform for Application Deployment (Optional)

For a production-like workflow using Terraform as described in `helm/README.md`:

**Create dev-specific Terraform configuration**:
```powershell
# Navigate to terraform directory
cd terraform/homelab

# Create dev.tfvars
@"
domain = "homelab.local"
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
