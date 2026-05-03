output "route53_nameservers" {
  description = "Route 53 nameservers to configure at your domain registrar"
  value       = module.route53.nameservers
}

output "ingress_tunnel_public_ip" {
  description = "Elastic IP address of the EC2 ingress tunnel node"
  value       = module.ingress_tunnel.public_ip
}

output "ingress_tunnel_instance_id" {
  description = "EC2 instance ID of the ingress tunnel node"
  value       = module.ingress_tunnel.instance_id
}

output "state_bucket_name" {
  description = "S3 bucket name for Terraform remote state"
  value       = module.state_backend.bucket_name
}

output "secret_arns" {
  description = "ARNs of all Secrets Manager secrets created"
  value       = module.secrets.secret_arns
}
