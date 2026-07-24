# Managed alternative to k8s/minio/deployment.yaml's self-hosted MinIO —
# the cloud-native home for raw PDFs/scanned images/OCR artifacts/markup
# outputs (src/storage/blob_store.py's BlobStore interface). Using this in
# place of MinIO would mean adding a GCSBlobStore implementation there
# (not built yet — the interface exists specifically so that's an addition,
# not a rewrite, when it's actually needed).
resource "google_storage_bucket" "blobs" {
  name          = "${var.project_id}-delta-chat-blobs-${var.environment}"
  location      = var.gcs_bucket_location
  storage_class = "STANDARD"

  uniform_bucket_level_access = true
  force_destroy               = var.gcs_force_destroy

  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      age = 90
      # Only expires OLDER NONCURRENT versions (i.e. superseded revisions
      # kept around by the versioning block above), never the current
      # object — cost control on version history, not a TTL on the data
      # itself, which is exactly the wrong default for "the only copy of a
      # source PDF."
      with_state = "ARCHIVED"
    }
    action {
      type = "Delete"
    }
  }

  labels = var.labels
}
