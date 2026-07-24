# Every API this config's resources actually need enabled. Listed
# explicitly (rather than assuming they're already on) so `terraform plan`
# against a brand-new project fails with a clear "API not enabled, here's
# which one" instead of a cryptic 403 partway through applying something else.
resource "google_project_service" "required" {
  for_each = toset([
    "container.googleapis.com",        # GKE
    "artifactregistry.googleapis.com", # Docker image repo
    "redis.googleapis.com",            # Memorystore
    "storage.googleapis.com",          # GCS
    "secretmanager.googleapis.com",    # Secret Manager
    "compute.googleapis.com",          # VPC/networking, backing GKE+Memorystore
    "iam.googleapis.com",
    "monitoring.googleapis.com", # Cloud Monitoring (optional alongside in-cluster Prometheus)
    "logging.googleapis.com",
  ])

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}
