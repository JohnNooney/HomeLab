output "public_ip" {
  description = "Elastic IP address of the ingress tunnel node"
  value       = aws_eip.ingress_tunnel.public_ip
}

output "instance_id" {
  description = "EC2 instance ID"
  value       = aws_instance.ingress_tunnel.id
}

output "vpc_id" {
  description = "VPC ID"
  value       = aws_vpc.main.id
}

output "security_group_id" {
  description = "Security group ID for the ingress tunnel"
  value       = aws_security_group.ingress_tunnel.id
}

output "iam_role_arn" {
  description = "ARN of the EC2 IAM role"
  value       = aws_iam_role.ingress_tunnel.arn
}
