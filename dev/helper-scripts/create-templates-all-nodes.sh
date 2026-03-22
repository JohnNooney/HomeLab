#!/bin/bash

# Automated Template Creation Script for All Proxmox Nodes
# This script creates Ubuntu K8s templates on all Proxmox nodes with unique IDs
#
# Usage:
#   chmod +x create-templates-all-nodes.sh
#   ./create-templates-all-nodes.sh

# Configuration
CLOUD_IMAGE_URL="https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.img"
CLOUD_IMAGE_NAME="jammy-server-cloudimg-amd64.img"

# Node configuration - Add your Proxmox nodes here
declare -A NODES
NODES["pve"]="172.25.37.31:9000"      # Format: IP:TEMPLATE_ID
NODES["pve2"]="172.25.40.129:9001"    # Each node gets unique template ID

# Function to create template on a specific node
create_template_on_node() {
    local NODE_NAME=$1
    local NODE_CONFIG=$2
    local NODE_IP="${NODE_CONFIG%%:*}"
    local TEMPLATE_ID="${NODE_CONFIG##*:}"
    
    echo "=========================================="
    echo "Creating template on node: $NODE_NAME"
    echo "Node IP: $NODE_IP"
    echo "Template ID: $TEMPLATE_ID"
    echo "=========================================="
    
    # SSH into node and create template
    ssh root@$NODE_IP bash << EOF
set -e

# Download cloud image if not exists
if [ ! -f /var/lib/vz/template/iso/$CLOUD_IMAGE_NAME ]; then
    echo "Downloading Ubuntu cloud image..."
    cd /var/lib/vz/template/iso
    wget -q --show-progress $CLOUD_IMAGE_URL
else
    echo "Cloud image already exists, skipping download"
fi

# Check if template already exists
if qm status $TEMPLATE_ID &>/dev/null; then
    echo "Template $TEMPLATE_ID already exists on $NODE_NAME"
    echo "Skipping template creation"
    exit 0
fi

# Create VM
echo "Creating VM with ID $TEMPLATE_ID..."
qm create $TEMPLATE_ID --name ubuntu-k8s-template --memory 4096 --cores 2 --net0 virtio,bridge=vmbr0

# Import cloud image as disk
echo "Importing cloud image..."
qm importdisk $TEMPLATE_ID /var/lib/vz/template/iso/$CLOUD_IMAGE_NAME local-lvm

# Attach disk to VM
echo "Configuring VM..."
qm set $TEMPLATE_ID --scsihw virtio-scsi-pci --scsi0 local-lvm:vm-$TEMPLATE_ID-disk-0

# Add cloud-init drive
qm set $TEMPLATE_ID --ide2 local-lvm:cloudinit

# Configure boot
qm set $TEMPLATE_ID --boot c --bootdisk scsi0

# Add serial console
qm set $TEMPLATE_ID --serial0 socket --vga serial0

# Enable QEMU guest agent
qm set $TEMPLATE_ID --agent enabled=1

# Convert to template
echo "Converting to template..."
qm template $TEMPLATE_ID

echo "Template $TEMPLATE_ID created successfully on $NODE_NAME"
EOF
    
    if [ $? -eq 0 ]; then
        echo "✓ Template creation successful on $NODE_NAME"
    else
        echo "✗ Template creation failed on $NODE_NAME"
        return 1
    fi
    echo ""
}

# Main execution
echo "Starting template creation on all Proxmox nodes..."
echo ""

FAILED_NODES=()

for NODE_NAME in "${!NODES[@]}"; do
    if ! create_template_on_node "$NODE_NAME" "${NODES[$NODE_NAME]}"; then
        FAILED_NODES+=("$NODE_NAME")
    fi
done

# Summary
echo "=========================================="
echo "Template Creation Summary"
echo "=========================================="

if [ ${#FAILED_NODES[@]} -eq 0 ]; then
    echo "✓ All templates created successfully!"
    echo ""
    echo "Template IDs:"
    for NODE_NAME in "${!NODES[@]}"; do
        TEMPLATE_ID="${NODES[$NODE_NAME]##*:}"
        echo "  - $NODE_NAME: Template ID $TEMPLATE_ID"
    done
else
    echo "✗ Template creation failed on the following nodes:"
    for NODE in "${FAILED_NODES[@]}"; do
        echo "  - $NODE"
    done
    exit 1
fi
