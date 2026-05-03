variable "aws_region" {
  description = "AWS region to deploy resources into"
  type        = string
  default     = "eu-west-2"
}

variable "project_name" {
  description = "Project name used for resource naming and tagging"
  type        = string
  default     = "homelab"
}

variable "domain_name" {
  description = "Primary domain name for the Route 53 hosted zone"
  type        = string
  default     = "nooney.dev"
}

variable "ssh_allowed_cidr" {
  description = "CIDR block allowed to SSH to the EC2 ingress tunnel instance (e.g. YOUR_IP/32)"
  type        = string
}
