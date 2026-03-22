#!/bin/bash

# Kubernetes Cluster VM Creation Script
# This script clones VMs from the ubuntu-k8s-template and configures them for a K8s cluster
#
# Prerequisites:
# 1. Run create-k8s-template.sh first to create the base template
# 2. Generate SSH key pair on your Windows host:
#    ssh-keygen -t rsa -b 4096 -C "homelab-dev" -f "$env:USERPROFILE\.ssh\homelab-dev"
# 3. Replace SSH_KEY below with your public key content from step 2
#
# Usage:
#   chmod +x create-k8s-cluster.sh
#   ./create-k8s-cluster.sh

# Variables
TEMPLATE_ID=9000
SSH_KEY="ssh-rsa AAAAB3... your-key-here"  # REPLACE THIS with your actual public key!

# Function to create VM
create_vm() {
    local VM_ID=$1
    local VM_NAME=$2
    local IP_ADDRESS=$3
    
    # Clone template
    qm clone $TEMPLATE_ID $VM_ID --name $VM_NAME --full
    
    # Configure cloud-init
    qm set $VM_ID --ipconfig0 ip=$IP_ADDRESS/24,gw=192.168.100.1
    qm set $VM_ID --nameserver 8.8.8.8
    qm set $VM_ID --sshkeys <(echo "$SSH_KEY")
    qm set $VM_ID --ciuser ubuntu
    
    # Resize disk
    qm resize $VM_ID scsi0 +20G
    
    # Start VM
    qm start $VM_ID
    
    echo "Created VM: $VM_NAME ($VM_ID) - $IP_ADDRESS"
}

# Create control plane nodes
create_vm 101 "k8s-control-01" "192.168.100.21"

# Create worker nodes
create_vm 201 "k8s-worker-01" "192.168.100.31"
create_vm 202 "k8s-worker-02" "192.168.100.32"
create_vm 203 "k8s-worker-03" "192.168.100.33"

echo "Kubernetes cluster VMs created successfully"
echo "Wait 2-3 minutes for cloud-init to complete"