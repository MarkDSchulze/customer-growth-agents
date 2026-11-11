output "cluster_name" { value = aws_eks_cluster.regional.name }
output "database_endpoint" { value = aws_db_instance.operational.address }
output "database_admin_secret_arn" {
  value     = aws_db_instance.operational.master_user_secret[0].secret_arn
  sensitive = true
}
output "msk_cluster_arn" { value = aws_msk_serverless_cluster.regional.arn }
output "workload_role_arn" { value = aws_iam_role.workload["application"].arn }
output "runtime_secret_arn" { value = aws_secretsmanager_secret.runtime.arn }
output "audit_bucket" { value = aws_s3_bucket.audit.bucket }
output "kms_key_arn" { value = aws_kms_key.regional.arn }
