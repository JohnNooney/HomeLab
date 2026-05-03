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

### AWS Service Account Setup

Two IAM identities are required before running Terraform.

#### Terraform Operator (IAM User)

This user runs all Terraform operations locally.

**Step 1 — Create the IAM user**
```bash
aws iam create-user --user-name homelab-terraform
```
> Take note of the `Arn` returned from this command as it will be needed in the next step for attaching the policy.

**Step 2 — Attach a permissions policy**

Use the `terraform-policy.json` in this directory to attach it to the `homelab-terraform` user:
```bash
aws iam create-policy \
  --policy-name homelab-terraform-policy \
  --policy-document file://terraform-policy.json

aws iam attach-user-policy \
  --user-name homelab-terraform \
  --policy-arn arn:aws:iam::<ACCOUNT_ID>:policy/homelab-terraform-policy
```

**Step 3 — Generate access keys**
```bash
aws iam create-access-key --user-name homelab-terraform
```

**Step 4 — Configure the AWS CLI**
```bash
aws configure --profile homelab-terraform
# Enter the access key ID, secret access key, region (eu-west-2), and output format (json)

# Export the profile for Terraform to pick up
export AWS_PROFILE=homelab-terraform
```

---

#### External Secrets Operator — ESO (IAM User)

This user is used by the External Secrets Operator running in the Kubernetes cluster to pull secrets from Secrets Manager.

**Step 1 — Create the IAM user**
```bash
aws iam create-user --user-name homelab-eso
```

**Step 2 — Attach a read-only Secrets Manager policy**
```bash
aws iam put-user-policy \
  --user-name homelab-eso \
  --policy-name homelab-eso-secrets-read \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue",
        "secretsmanager:DescribeSecret",
        "secretsmanager:ListSecrets"
      ],
      "Resource": "arn:aws:secretsmanager:eu-west-2:*:secret:/homelab/*"
    }]
  }'
```

**Step 3 — Generate access keys and store in Kubernetes**
```bash
aws iam create-access-key --user-name homelab-eso
# Store the output — these credentials are used by the ESO ClusterSecretStore

kubectl create secret generic aws-credentials \
  --namespace <namespace> \
  --from-literal=access-key=<ACCESS_KEY_ID> \
  --from-literal=secret-access-key=<SECRET_ACCESS_KEY>
```

---

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
- S3 bucket for Terraform state storage (with versioning enabled, S3-native locking via `use_lockfile = true`)

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
