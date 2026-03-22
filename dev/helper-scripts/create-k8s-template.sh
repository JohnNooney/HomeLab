#!/bin/bash

# Variables
TEMPLATE_ID=9000
TEMPLATE_NAME="ubuntu-k8s-template"
CLOUD_IMAGE="/var/lib/vz/template/iso/jammy-server-cloudimg-amd64.img"

# Create VM
qm create $TEMPLATE_ID --name $TEMPLATE_NAME --memory 4096 --cores 2 --net0 virtio,bridge=vmbr0

# Import cloud image as disk
qm importdisk $TEMPLATE_ID $CLOUD_IMAGE local-lvm

# Attach disk to VM
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
qm template $TEMPLATE_ID

echo "Template $TEMPLATE_NAME created with ID $TEMPLATE_ID"