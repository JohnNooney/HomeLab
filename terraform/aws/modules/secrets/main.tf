resource "aws_secretsmanager_secret" "plex_claim_token" {
  name                    = "/${var.project_name}/plex/claim_token"
  description             = "Plex claim token for server registration"
  recovery_window_in_days = 7

  tags = {
    Application = "plex"
  }
}

resource "aws_secretsmanager_secret" "transmission_wireguard_config" {
  name                    = "/${var.project_name}/transmission/wireguard_config"
  description             = "WireGuard VPN config for Transmission — full wg0.conf contents"
  recovery_window_in_days = 7

  tags = {
    Application = "transmission"
  }
}

resource "aws_secretsmanager_secret" "tailscale_auth_key" {
  name                    = "/${var.project_name}/tailscale/auth_key"
  description             = "Tailscale auth key used by the EC2 ingress tunnel node at boot"
  recovery_window_in_days = 7

  tags = {
    Application = "tailscale"
  }
}
