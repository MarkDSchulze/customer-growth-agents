data "aws_caller_identity" "current" {}
data "aws_subnet" "private" {
  for_each = toset(var.private_subnet_ids)
  id       = each.value
}
resource "aws_kms_key" "regional" {
  description             = "Regional growth encryption and immutable audit"
  enable_key_rotation     = true
  deletion_window_in_days = 30
}
resource "aws_kms_alias" "regional" {
  name          = "alias/${var.name}-${var.region}"
  target_key_id = aws_kms_key.regional.key_id
}
resource "aws_iam_role" "cluster" {
  name = "${var.name}-eks-${var.region}"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Principal = { Service = "eks.amazonaws.com" }, Action = "sts:AssumeRole"
  }] })
}
resource "aws_iam_role_policy_attachment" "cluster" {
  role       = aws_iam_role.cluster.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
}
resource "aws_eks_cluster" "regional" {
  name     = var.name
  role_arn = aws_iam_role.cluster.arn
  version  = var.kubernetes_version
  vpc_config {
    subnet_ids              = var.private_subnet_ids
    endpoint_private_access = true
    endpoint_public_access  = false
  }
  encryption_config {
    provider { key_arn = aws_kms_key.regional.arn }
    resources = ["secrets"]
  }
  enabled_cluster_log_types = ["api", "audit", "authenticator", "controllerManager", "scheduler"]
  access_config { authentication_mode = "API_AND_CONFIG_MAP" }
  lifecycle {
    precondition {
      condition     = length(toset([for s in data.aws_subnet.private : s.availability_zone])) >= 3
      error_message = "Subnets must span three availability zones."
    }
    precondition {
      condition     = alltrue([for s in data.aws_subnet.private : s.vpc_id == var.vpc_id && !s.map_public_ip_on_launch])
      error_message = "Subnets must be private and belong to the supplied VPC."
    }
  }
  depends_on = [aws_iam_role_policy_attachment.cluster]
}
resource "aws_iam_openid_connect_provider" "eks" {
  url            = aws_eks_cluster.regional.identity[0].oidc[0].issuer
  client_id_list = ["sts.amazonaws.com"]
}
locals {
  oidc_host = replace(aws_iam_openid_connect_provider.eks.url, "https://", "")
  subjects = {
    application = "system:serviceaccount:${var.namespace}:growth-runtime"
    cni         = "system:serviceaccount:kube-system:aws-node"
  }
}
resource "aws_iam_role" "workload" {
  for_each = local.subjects
  name     = "${var.name}-${each.key}-${var.region}"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Principal = { Federated = aws_iam_openid_connect_provider.eks.arn },
    Action = "sts:AssumeRoleWithWebIdentity", Condition = { StringEquals = {
      "${local.oidc_host}:sub" = each.value, "${local.oidc_host}:aud" = "sts.amazonaws.com"
    } }
  }] })
}
resource "aws_iam_role_policy_attachment" "cni" {
  role       = aws_iam_role.workload["cni"].name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy"
}
resource "aws_eks_addon" "vpc_cni" {
  cluster_name                = aws_eks_cluster.regional.name
  addon_name                  = "vpc-cni"
  service_account_role_arn    = aws_iam_role.workload["cni"].arn
  configuration_values        = jsonencode({ enableNetworkPolicy = "true" })
  resolve_conflicts_on_update = "PRESERVE"
}
resource "aws_iam_role" "nodes" {
  name = "${var.name}-nodes-${var.region}"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Principal = { Service = "ec2.amazonaws.com" }, Action = "sts:AssumeRole"
  }] })
}
resource "aws_iam_role_policy_attachment" "nodes" {
  for_each   = toset(["AmazonEKSWorkerNodePolicy", "AmazonEC2ContainerRegistryPullOnly"])
  role       = aws_iam_role.nodes.name
  policy_arn = "arn:aws:iam::aws:policy/${each.value}"
}
resource "aws_launch_template" "nodes" {
  name_prefix = "${var.name}-"
  metadata_options {
    http_tokens                 = "required"
    http_endpoint               = "enabled"
    http_put_response_hop_limit = 1
  }
  block_device_mappings {
    device_name = "/dev/xvda"
    ebs {
      volume_size           = 50
      volume_type           = "gp3"
      encrypted             = true
      delete_on_termination = true
    }
  }
}
resource "aws_eks_node_group" "regional" {
  cluster_name    = aws_eks_cluster.regional.name
  node_group_name = "${var.name}-regional"
  node_role_arn   = aws_iam_role.nodes.arn
  subnet_ids      = var.private_subnet_ids
  instance_types  = var.instance_types
  launch_template {
    id      = aws_launch_template.nodes.id
    version = aws_launch_template.nodes.latest_version
  }
  scaling_config {
    desired_size = var.min_nodes
    min_size     = var.min_nodes
    max_size     = var.max_nodes
  }
  update_config { max_unavailable = 1 }
  depends_on = [aws_iam_role_policy_attachment.nodes, aws_eks_addon.vpc_cni]
}
resource "aws_security_group" "data" {
  name_prefix = "${var.name}-data-"
  description = "Regional growth data services"
  vpc_id      = var.vpc_id
}
resource "aws_vpc_security_group_ingress_rule" "postgres" {
  security_group_id            = aws_security_group.data.id
  referenced_security_group_id = aws_eks_cluster.regional.vpc_config[0].cluster_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}
resource "aws_vpc_security_group_ingress_rule" "kafka" {
  security_group_id            = aws_security_group.data.id
  referenced_security_group_id = aws_eks_cluster.regional.vpc_config[0].cluster_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = 9098
  to_port                      = 9098
}
resource "aws_db_subnet_group" "regional" {
  name       = "${var.name}-regional"
  subnet_ids = var.private_subnet_ids
}
resource "aws_db_parameter_group" "regional" {
  name_prefix = "${var.name}-"
  family      = "postgres16"
  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }
}
resource "aws_db_instance" "operational" {
  identifier                      = "${var.name}-operational"
  engine                          = "postgres"
  engine_version                  = "16.11"
  instance_class                  = "db.r7g.large"
  allocated_storage               = 100
  max_allocated_storage           = 1000
  storage_type                    = "gp3"
  storage_encrypted               = true
  kms_key_id                      = aws_kms_key.regional.arn
  db_name                         = "growth"
  username                        = "growth_owner"
  manage_master_user_password     = true
  multi_az                        = true
  publicly_accessible             = false
  db_subnet_group_name            = aws_db_subnet_group.regional.name
  parameter_group_name            = aws_db_parameter_group.regional.name
  vpc_security_group_ids          = [aws_security_group.data.id]
  backup_retention_period         = 35
  deletion_protection             = true
  skip_final_snapshot             = false
  final_snapshot_identifier       = "${var.name}-final-snapshot"
  performance_insights_enabled    = true
  performance_insights_kms_key_id = aws_kms_key.regional.arn
  enabled_cloudwatch_logs_exports = ["postgresql", "upgrade"]
}
resource "aws_msk_serverless_cluster" "regional" {
  cluster_name = "${var.name}-signals"
  vpc_config {
    subnet_ids         = var.private_subnet_ids
    security_group_ids = [aws_security_group.data.id]
  }
  client_authentication {
    sasl {
      iam { enabled = true }
    }
  }
}
resource "aws_secretsmanager_secret" "runtime" {
  name                    = "${var.name}/${var.region}/runtime"
  kms_key_id              = aws_kms_key.regional.arn
  recovery_window_in_days = 30
}
resource "aws_s3_bucket" "audit" {
  bucket              = "${var.name}-${data.aws_caller_identity.current.account_id}-${var.region}-audit"
  object_lock_enabled = true
}
resource "aws_s3_bucket_versioning" "audit" {
  bucket = aws_s3_bucket.audit.id
  versioning_configuration { status = "Enabled" }
}
resource "aws_s3_bucket_object_lock_configuration" "audit" {
  bucket = aws_s3_bucket.audit.id
  rule {
    default_retention {
      mode = "COMPLIANCE"
      days = 365
    }
  }
  depends_on = [aws_s3_bucket_versioning.audit]
}
resource "aws_s3_bucket_public_access_block" "audit" {
  bucket                  = aws_s3_bucket.audit.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_server_side_encryption_configuration" "audit" {
  bucket = aws_s3_bucket.audit.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.regional.arn
    }
    bucket_key_enabled = true
  }
}
resource "aws_s3_bucket_policy" "audit_tls" {
  bucket = aws_s3_bucket.audit.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect    = "Deny", Principal = "*", Action = "s3:*",
    Resource  = [aws_s3_bucket.audit.arn, "${aws_s3_bucket.audit.arn}/*"],
    Condition = { Bool = { "aws:SecureTransport" = "false" } }
  }] })
}
resource "aws_iam_role_policy" "application" {
  role = aws_iam_role.workload["application"].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = [aws_secretsmanager_secret.runtime.arn] },
    { Effect = "Allow", Action = ["kms:Decrypt", "kms:GenerateDataKey"], Resource = [aws_kms_key.regional.arn] },
    { Effect = "Allow", Action = ["s3:PutObject", "s3:PutObjectRetention", "s3:GetObject"], Resource = ["${aws_s3_bucket.audit.arn}/*"] },
    { Effect = "Allow", Action = ["kafka-cluster:Connect", "kafka-cluster:DescribeCluster", "kafka-cluster:WriteDataIdempotently"], Resource = [aws_msk_serverless_cluster.regional.arn] },
    { Effect = "Allow", Action = ["kafka-cluster:CreateTopic", "kafka-cluster:DescribeTopic", "kafka-cluster:WriteData", "kafka-cluster:ReadData"], Resource = ["${replace(aws_msk_serverless_cluster.regional.arn, ":cluster/", ":topic/")}/*"] },
    { Effect = "Allow", Action = ["kafka-cluster:AlterGroup", "kafka-cluster:DescribeGroup"], Resource = ["${replace(aws_msk_serverless_cluster.regional.arn, ":cluster/", ":group/")}/*"] }
  ] })
}
