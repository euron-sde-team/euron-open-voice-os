# One private bucket for objects too large to keep in Postgres: session audio (only when
# an agent opts in with store_audio; off by default) and benchmark reports. Rows hold only
# the object key. Audio is personal data, so it expires on a fixed schedule instead of
# being versioned and kept.
resource "aws_s3_bucket" "objects" {
  #checkov:skip=CKV_AWS_144:Cross-region replication would copy personal audio to a second region; objects are short-lived by design.
  #checkov:skip=CKV_AWS_18:Access logging targets a separate log bucket an operator chooses; CloudTrail data events cover object access (docs/guides/operations.md).
  #checkov:skip=CKV2_AWS_62:No consumer for S3 event notifications.
  #checkov:skip=CKV_AWS_21:Objects expire after expiration_days; versioning would keep deleted audio, defeating erasure.
  bucket        = "${var.name_prefix}-objects"
  force_destroy = var.force_destroy
}

resource "aws_s3_bucket_public_access_block" "objects" {
  bucket                  = aws_s3_bucket.objects.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "objects" {
  bucket = aws_s3_bucket.objects.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "objects" {
  bucket = aws_s3_bucket.objects.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = var.kms_key_arn != null ? "aws:kms" : "AES256"
      kms_master_key_id = var.kms_key_arn
    }
    bucket_key_enabled = var.kms_key_arn != null
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "objects" {
  bucket = aws_s3_bucket.objects.id

  rule {
    id     = "abort-incomplete-multipart"
    status = "Enabled"
    filter {}
    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }

  # Session audio is the caller's voice: keep it only as long as the retention allows,
  # whatever the agent's own setting says (the API erases earlier when asked).
  dynamic "rule" {
    for_each = toset(["audio/"])
    content {
      id     = "expire-${trim(rule.value, "/")}"
      status = "Enabled"
      filter {
        prefix = rule.value
      }
      expiration {
        days = var.expiration_days
      }
    }
  }

  # Benchmark reports hold synthesized test speech and timings only; keep them longer for comparison.
  rule {
    id     = "expire-benchmarks"
    status = "Enabled"
    filter {
      prefix = "benchmarks/"
    }
    expiration {
      days = var.report_expiration_days
    }
  }
}

# Only needed when a browser fetches objects with JavaScript; a presigned download link
# opened as a navigation needs none, so the default is no CORS at all.
resource "aws_s3_bucket_cors_configuration" "objects" {
  count  = length(var.cors_origins) > 0 ? 1 : 0
  bucket = aws_s3_bucket.objects.id
  cors_rule {
    allowed_methods = ["GET", "HEAD"]
    allowed_origins = var.cors_origins
    allowed_headers = ["*"]
    expose_headers  = ["Content-Disposition", "Content-Length", "ETag"]
    max_age_seconds = 3600
  }
}

data "aws_iam_policy_document" "objects" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.objects.arn, "${aws_s3_bucket.objects.arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "objects" {
  count      = var.enforce_tls ? 1 : 0
  bucket     = aws_s3_bucket.objects.id
  policy     = data.aws_iam_policy_document.objects.json
  depends_on = [aws_s3_bucket_public_access_block.objects]
}
