output "bucket_name" {
  description = "Objects bucket name (OBJECTS_BUCKET)."
  value       = aws_s3_bucket.objects.bucket
}

output "bucket_arn" {
  description = "Objects bucket ARN, for IAM policies."
  value       = aws_s3_bucket.objects.arn
}
