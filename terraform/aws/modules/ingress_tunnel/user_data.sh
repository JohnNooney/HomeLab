#!/bin/bash
set -euo pipefail

# Install Tailscale
curl -fsSL https://tailscale.com/install.sh | sh

# Fetch Tailscale auth key from Secrets Manager
TAILSCALE_AUTH_KEY=$(aws secretsmanager get-secret-value \
  --region "${aws_region}" \
  --secret-id "${tailscale_auth_key_secret_arn}" \
  --query SecretString \
  --output text)

# Enable IP forwarding (required for Tailscale exit node / subnet routing)
echo 'net.ipv4.ip_forward = 1' | tee /etc/sysctl.d/99-tailscale.conf
echo 'net.ipv6.conf.all.forwarding = 1' | tee -a /etc/sysctl.d/99-tailscale.conf
sysctl -p /etc/sysctl.d/99-tailscale.conf

# Authenticate and bring up Tailscale
tailscale up \
  --authkey="$TAILSCALE_AUTH_KEY" \
  --advertise-exit-node \
  --ssh

# Enable automatic security updates
dnf install -y dnf-automatic
sed -i 's/^apply_updates = no/apply_updates = yes/' /etc/dnf/automatic.conf
systemctl enable --now dnf-automatic.timer
