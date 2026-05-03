output "plex_claim_token_arn" {
  description = "ARN of the Plex claim token secret"
  value       = aws_secretsmanager_secret.plex_claim_token.arn
}

output "transmission_wireguard_config_arn" {
  description = "ARN of the Transmission WireGuard config secret"
  value       = aws_secretsmanager_secret.transmission_wireguard_config.arn
}

output "tailscale_auth_key_arn" {
  description = "ARN of the Tailscale auth key secret"
  value       = aws_secretsmanager_secret.tailscale_auth_key.arn
}

output "secret_arns" {
  description = "Map of all secret ARNs"
  value = {
    plex_claim_token              = aws_secretsmanager_secret.plex_claim_token.arn
    transmission_wireguard_config = aws_secretsmanager_secret.transmission_wireguard_config.arn
    tailscale_auth_key            = aws_secretsmanager_secret.tailscale_auth_key.arn
  }
}
