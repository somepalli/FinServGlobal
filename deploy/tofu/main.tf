# Demo topology for the FinServ compliance assistant.
#
# OpenTofu, not Terraform. Terraform 1.6+ ships under BUSL 1.1, which is
# source-available rather than OSI open source, and the assignment restricts us
# to open source. OpenTofu is MPL 2.0 under the Linux Foundation and the HCL is
# unchanged. See docs/adr/005-iac-tool.md.
#
# ap-south-1 on purpose: the design pins Indian regulated corpora and their
# inference to Mumbai, so the demo runs where the architecture says it should.
#
# This is a demo cluster, not the production topology described in the
# architecture document. Differences are listed in deploy/README.md.
# Public subnets only, no NAT gateway - a NAT would add roughly $33/month for
# no demo value. Node security groups restrict ingress to the ALB.

terraform {
  required_version = ">= 1.9"  # OpenTofu
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.70"
    }
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project   = "finserv-compliance"
      ManagedBy = "terraform"
      Ephemeral = "true"
    }
  }
}

locals {
  name = "finserv-compliance"
  azs  = ["${var.region}a", "${var.region}b"]
}

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.13"

  name                 = local.name
  cidr                 = "10.0.0.0/16"
  azs                  = local.azs
  public_subnets       = ["10.0.1.0/24", "10.0.2.0/24"]
  enable_nat_gateway   = false
  enable_dns_hostnames = true

  public_subnet_tags = {
    "kubernetes.io/role/elb" = 1
  }
}

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.31"

  cluster_name                   = local.name
  cluster_version                = "1.31"
  cluster_endpoint_public_access = true

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.public_subnets

  enable_cluster_creator_admin_permissions = true

  cluster_addons = {
    coredns                = {}
    kube-proxy             = {}
    vpc-cni                = {}
    aws-ebs-csi-driver     = {}
  }

  eks_managed_node_groups = {
    # API, frontend, Qdrant. Always on.
    platform = {
      instance_types = ["t3.large"]
      min_size       = 2
      max_size       = 3
      desired_size   = 2
      subnet_ids     = module.vpc.public_subnets
    }

    # vLLM. Scaled to zero between demo runs - this is the expensive one.
    inference = {
      instance_types = ["g5.xlarge"]
      ami_type       = "AL2_x86_64_GPU"
      min_size       = 0
      max_size       = 1
      desired_size   = var.gpu_desired_size
      subnet_ids     = [module.vpc.public_subnets[0]]

      labels = { workload = "inference" }
      taints = [{
        key    = "nvidia.com/gpu"
        value  = "true"
        effect = "NO_SCHEDULE"
      }]
    }
  }
}

resource "aws_ecr_repository" "api" {
  name                 = "compliance-api"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_repository" "web" {
  name                 = "compliance-web"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_s3_bucket" "corpus" {
  bucket = "${local.name}-corpus-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_server_side_encryption_configuration" "corpus" {
  bucket = aws_s3_bucket.corpus.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "corpus" {
  bucket                  = aws_s3_bucket.corpus.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

data "aws_caller_identity" "current" {}
