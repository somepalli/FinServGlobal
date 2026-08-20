output "cluster_name" {
  value = module.eks.cluster_name
}

output "ecr_api" {
  value = aws_ecr_repository.api.repository_url
}

output "corpus_bucket" {
  value = aws_s3_bucket.corpus.bucket
}

output "kubeconfig_command" {
  value = "aws eks update-kubeconfig --region ${var.region} --name ${module.eks.cluster_name}"
}
