module "state_backend" {
  source = "./modules/state_backend"

  project_name = var.project_name
  aws_region   = var.aws_region
}

module "route53" {
  source = "./modules/route53"

  domain_name  = var.domain_name
  project_name = var.project_name
}

module "secrets" {
  source = "./modules/secrets"

  project_name = var.project_name
}

module "ingress_tunnel" {
  source = "./modules/ingress_tunnel"

  project_name                  = var.project_name
  aws_region                    = var.aws_region
  ssh_allowed_cidr              = var.ssh_allowed_cidr
  tailscale_auth_key_secret_arn = module.secrets.tailscale_auth_key_arn
}
