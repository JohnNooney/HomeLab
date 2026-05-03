# --- VPC & Networking ---

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name = "${var.project_name}-vpc"
  }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "${var.project_name}-igw"
  }
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = var.public_subnet_cidr
  map_public_ip_on_launch = false

  tags = {
    Name = "${var.project_name}-public-subnet"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = {
    Name = "${var.project_name}-public-rt"
  }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

# --- Security Group ---

resource "aws_security_group" "ingress_tunnel" {
  name        = "${var.project_name}-ingress-tunnel-sg"
  description = "Security group for the EC2 ingress tunnel node"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "SSH - restrict to known IP via ssh_allowed_cidr variable"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.ssh_allowed_cidr]
  }

  ingress {
    description = "HTTPS inbound for reverse proxy"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTP inbound for reverse proxy"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "Tailscale UDP"
    from_port   = 41641
    to_port     = 41641
    protocol    = "udp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "Allow all outbound traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-ingress-tunnel-sg"
  }
}

# --- IAM Role & Instance Profile ---

data "aws_iam_policy_document" "ec2_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ingress_tunnel" {
  name               = "${var.project_name}-ingress-tunnel-role"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume_role.json

  tags = {
    Name = "${var.project_name}-ingress-tunnel-role"
  }
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.ingress_tunnel.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy_attachment" "cloudwatch" {
  role       = aws_iam_role.ingress_tunnel.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
}

data "aws_iam_policy_document" "secrets_read" {
  statement {
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [var.tailscale_auth_key_secret_arn]
  }
}

resource "aws_iam_role_policy" "secrets_read" {
  name   = "${var.project_name}-ingress-tunnel-secrets"
  role   = aws_iam_role.ingress_tunnel.id
  policy = data.aws_iam_policy_document.secrets_read.json
}

resource "aws_iam_instance_profile" "ingress_tunnel" {
  name = "${var.project_name}-ingress-tunnel-profile"
  role = aws_iam_role.ingress_tunnel.name
}

# --- AMI: Amazon Linux 2023 ARM64 (latest via SSM Parameter) ---

data "aws_ssm_parameter" "amazon_linux_2023_arm64" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64"
}

# --- EC2 Instance ---

resource "aws_instance" "ingress_tunnel" {
  ami                    = data.aws_ssm_parameter.amazon_linux_2023_arm64.value
  instance_type          = var.instance_type
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.ingress_tunnel.id]
  iam_instance_profile   = aws_iam_instance_profile.ingress_tunnel.name

  user_data = templatefile("${path.module}/user_data.sh", {
    tailscale_auth_key_secret_arn = var.tailscale_auth_key_secret_arn
    aws_region                    = var.aws_region
  })

  root_block_device {
    volume_type           = "gp3"
    volume_size           = 8
    delete_on_termination = true
    encrypted             = true
  }

  metadata_options {
    http_tokens = "required"
  }

  tags = {
    Name = "${var.project_name}-ingress-tunnel"
  }
}

# --- Elastic IP ---

resource "aws_eip" "ingress_tunnel" {
  instance = aws_instance.ingress_tunnel.id
  domain   = "vpc"

  tags = {
    Name = "${var.project_name}-ingress-tunnel-eip"
  }

  depends_on = [aws_internet_gateway.main]
}
