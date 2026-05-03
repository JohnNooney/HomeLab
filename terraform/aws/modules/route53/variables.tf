variable "domain_name" {
  description = "Domain name for the Route 53 public hosted zone"
  type        = string
}

variable "project_name" {
  description = "Project name used for tagging"
  type        = string
}

variable "ingress_tunnel_eip" {
  description = "Elastic IP address of the EC2 ingress tunnel node, used for the wildcard homelab DNS record"
  type        = string
}
