# Overview
This directory contains the Terraform configuration for provisioning the AWS infrastructure for the HomeLab. Additionally this directory contains the Terraform modules used to provision the bare-metal application deployment infrastructure from the `../helm` directory.

## Phase 1: Cloud Foundation (Terraform)

This phase provisions the core AWS infrastructure required to support the HomeLab environment.

### Prerequisites
- AWS CLI configured with appropriate credentials
- Terraform >= 1.0 installed
- AWS account with sufficient permissions to create:
  - S3 buckets
  - DynamoDB tables
  - Route 53 hosted zones
  - Secrets Manager secrets
  - EC2 instances
  - VPC networking components

### Deployment Steps

#### 1.1 Terraform State Backend
**Purpose**: Create remote state storage for Terraform to enable team collaboration and state locking.

```bash
cd terraform/aws
terraform init
terraform plan -target=module.state_backend
terraform apply -target=module.state_backend
```

**Resources Created**:
- S3 bucket for Terraform state storage (with versioning enabled)
- DynamoDB table for state locking
- Appropriate IAM policies and encryption settings

#### 1.2 DNS Infrastructure
**Purpose**: Provision Route 53 hosted zones for domain management and DNS automation.

```bash
terraform plan -target=module.route53
terraform apply -target=module.route53
```

**Resources Created**:
- Route 53 public hosted zone(s) for your domain(s)
- NS records for domain delegation
- Initial DNS records as needed

**Post-Deployment**:
- Update your domain registrar with the Route 53 nameservers
- Verify DNS propagation before proceeding

#### 1.3 Secrets Management
**Purpose**: Create AWS Secrets Manager entries for sensitive configuration data.

```bash
terraform plan -target=module.secrets
terraform apply -target=module.secrets
```

**Resources Created**:
- AWS Secrets Manager secrets for:
  - Kubernetes cluster credentials
  - Application API keys
  - Database passwords
  - Tunnel/VPN credentials
  - External service tokens

**Note**: Populate secret values manually via AWS Console or CLI after creation.

#### 1.4 EC2 Ingress Tunnel Node
**Purpose**: Deploy an EC2 instance to serve as the ingress tunnel endpoint for the on-premises cluster.

```bash
terraform plan -target=module.ingress_tunnel
terraform apply -target=module.ingress_tunnel
```

**Resources Created**:
- EC2 instance (t3.micro or similar)
- Security groups with appropriate ingress/egress rules
- Elastic IP for stable public endpoint
- VPC and networking components
- IAM instance profile and roles
- User data script for initial configuration

**Configuration**:
- Wireguard or Tailscale VPN software
- Reverse proxy (nginx/caddy) for ingress traffic
- Automatic security updates
- CloudWatch logging

**Post-Deployment**:
- Note the Elastic IP address for tunnel configuration
- Retrieve VPN configuration from EC2 user data or Secrets Manager
- Test connectivity from local network

### Complete Infrastructure Deployment

Once individual components are verified, deploy the full infrastructure:

```bash
terraform plan
terraform apply
```

### Outputs

After successful deployment, Terraform will output:
- Route 53 nameservers
- EC2 ingress tunnel public IP
- S3 state bucket name
- DynamoDB lock table name
- Secrets Manager ARNs

### Validation

Verify the infrastructure:
```bash
# Check state backend
aws s3 ls s3://<state-bucket-name>

# Verify Route 53 hosted zone
aws route53 list-hosted-zones

# Check EC2 instance status
aws ec2 describe-instances --filters "Name=tag:Name,Values=ingress-tunnel"

# List secrets
aws secretsmanager list-secrets
```

## Phase 4: Application Deployment (Terraform + Helm)

Application workloads are deployed using Terraform to manage Helm chart releases. This approach provides:
- Infrastructure-as-code for application deployments
- Version control for application configurations
- Consistent deployment patterns
- Automated dependency management

See the `terraform/homelab/` directory for Helm chart deployments managed via Terraform.

### Structure
```
terraform/
├── aws/          # AWS cloud infrastructure
└── homelab/      # Kubernetes application deployments via Helm
```

For detailed application deployment steps, see `../helm/README.md`.
