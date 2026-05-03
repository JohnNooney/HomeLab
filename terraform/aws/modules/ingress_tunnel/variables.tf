variable "project_name" {
  description = "Project name used for resource naming and tagging"
  type        = string
}

variable "aws_region" {
  description = "AWS region"
  type        = string
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "public_subnet_cidr" {
  description = "CIDR block for the public subnet"
  type        = string
  default     = "10.0.1.0/24"
}

variable "instance_type" {
  description = "EC2 instance type (ARM64)"
  type        = string
  default     = "t4g.nano"
}

variable "ssh_allowed_cidr" {
  description = "CIDR block allowed SSH access to the instance (e.g. YOUR_IP/32)"
  type        = string
}

variable "tailscale_auth_key_secret_arn" {
  description = "ARN of the Secrets Manager secret containing the Tailscale auth key"
  type        = string
}
