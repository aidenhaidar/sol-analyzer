# AWS side of sol-analyzer: one VPC with a Solana RPC node (private) and an API host
# (public, TLS via Caddy) that the Cloudflare Worker calls.
terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.60" }
  }
}

provider "aws" {
  region = var.region
}

data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"]
  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }
}

# ------------------------------------------------------------------ network

resource "aws_vpc" "main" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_hostnames = true
  tags                 = { Name = "${var.name}-vpc" }
}

resource "aws_internet_gateway" "igw" {
  vpc_id = aws_vpc.main.id
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.0.1.0/24"
  availability_zone       = var.availability_zone
  map_public_ip_on_launch = true
  tags                    = { Name = "${var.name}-public" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.igw.id
  }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

# ------------------------------------------------------------------ security

resource "aws_security_group" "api" {
  name   = "${var.name}-api"
  vpc_id = aws_vpc.main.id
  # Cloudflare reaches the API over 443; 80 is only for the ACME challenge.
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = var.cloudflare_ipv4_cidrs
  }
  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = var.admin_cidrs
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "rpc" {
  name   = "${var.name}-rpc"
  vpc_id = aws_vpc.main.id
  # JSON-RPC + websocket only from the API host.
  ingress {
    from_port       = 8899
    to_port         = 8900
    protocol        = "tcp"
    security_groups = [aws_security_group.api.id]
  }
  # Gossip / TPU / repair ports the validator needs open to the cluster.
  ingress {
    from_port   = 8000
    to_port     = 8020
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    from_port   = 8000
    to_port     = 8020
    protocol    = "udp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = var.admin_cidrs
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# ------------------------------------------------------------------ RPC node

resource "aws_instance" "rpc" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.rpc_instance_type
  subnet_id              = aws_subnet.public.id
  private_ip             = "10.0.1.10"
  vpc_security_group_ids = [aws_security_group.rpc.id]
  key_name               = var.key_name
  user_data              = templatefile("${path.module}/rpc-node/user-data.sh", { cluster = var.solana_cluster })

  root_block_device {
    volume_size = 200
    volume_type = "gp3"
  }
  # Ledger and accounts live on separate NVMe volumes (see user-data.sh).
  ebs_block_device {
    device_name = "/dev/sdf"
    volume_size = var.ledger_volume_gb
    volume_type = "io2"
    iops        = 16000
  }
  ebs_block_device {
    device_name = "/dev/sdg"
    volume_size = var.accounts_volume_gb
    volume_type = "io2"
    iops        = 16000
  }
  tags = { Name = "${var.name}-rpc" }
}

# ------------------------------------------------------------------ API host

resource "aws_instance" "api" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.api_instance_type
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.api.id]
  key_name               = var.key_name
  user_data = templatefile("${path.module}/api-host/user-data.sh", {
    api_domain        = var.api_domain
    api_shared_secret = var.api_shared_secret
    api_image         = var.api_image
    rpc_private_ip    = aws_instance.rpc.private_ip
  })
  root_block_device {
    volume_size = 40
    volume_type = "gp3"
  }
  tags = { Name = "${var.name}-api" }
}

resource "aws_eip" "api" {
  instance = aws_instance.api.id
  domain   = "vpc"
}
