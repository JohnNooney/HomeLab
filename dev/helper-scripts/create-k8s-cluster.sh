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
SSH_KEY="ssh-rsa AAAAB3... your-key-here"  # REPLACE THIS with your actual public key!

# Node IP mapping - Update these with your actual Proxmox node IPs
declare -A NODE_IPS
NODE_IPS["pve-01"]="192.168.100.11"
NODE_IPS["pve-02"]="192.168.100.12"

# Template ID mapping - Each node has its own template with unique ID
declare -A TEMPLATE_IDS
TEMPLATE_IDS["pve-01"]=9000
TEMPLATE_IDS["pve-02"]=9001

# Function to create VM
create_vm() {
    local VM_ID=$1
    local VM_NAME=$2
    local IP_ADDRESS=$3
    local TARGET_NODE=$4
    
    echo "Creating VM $VM_NAME (ID: $VM_ID) on node $TARGET_NODE..."
    
    # Resolve node hostname to IP
    local NODE_IP="${NODE_IPS[$TARGET_NODE]}"
    if [ -z "$NODE_IP" ]; then
        echo "Error: No IP address configured for node $TARGET_NODE"
        return 1
    fi
    
    # Get template ID for this node
    local TEMPLATE_ID="${TEMPLATE_IDS[$TARGET_NODE]}"
    if [ -z "$TEMPLATE_ID" ]; then
        echo "Error: No template ID configured for node $TARGET_NODE"
        return 1
    fi
    
    echo "Using template ID $TEMPLATE_ID on node $TARGET_NODE"
    
    # Create temporary file with SSH key on target node
    echo "$SSH_KEY" | ssh root@$NODE_IP "cat > /tmp/ssh_key_$VM_ID.pub"
    
    # SSH into target node and execute all commands
    ssh root@$NODE_IP bash << EOF
# Clone template
qm clone $TEMPLATE_ID $VM_ID --name $VM_NAME --full

# Configure cloud-init
qm set $VM_ID --ipconfig0 ip=$IP_ADDRESS/24,gw=192.168.100.1
qm set $VM_ID --nameserver 8.8.8.8
qm set $VM_ID --sshkeys /tmp/ssh_key_$VM_ID.pub
qm set $VM_ID --ciuser ubuntu

# Resize disk (add 30GB to the 20GB template base = 50GB total)
qm resize $VM_ID scsi0 +30G

# Start VM
qm start $VM_ID

# Cleanup temp file
rm -f /tmp/ssh_key_$VM_ID.pub

echo "VM $VM_NAME created successfully"
EOF
    
    echo "Created VM: $VM_NAME ($VM_ID) - $IP_ADDRESS on $TARGET_NODE"
}

# Create control plane nodes
create_vm 101 "k8s-control-01" "192.168.100.21" "pve-01"

# Create worker nodes
create_vm 201 "k8s-worker-01" "192.168.100.31" "pve-01"
create_vm 202 "k8s-worker-02" "192.168.100.32" "pve-02"
create_vm 203 "k8s-worker-03" "192.168.100.33" "pve-02"

echo "Kubernetes cluster VMs created successfully"
echo "Wait 2-3 minutes for cloud-init to complete"