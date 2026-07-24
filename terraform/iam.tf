# Workload Identity: the k8s ServiceAccount "delta-chat-app" (namespace
# delta-chat, created by k8s/scripts/deploy.sh or manually — not by this
# Terraform config, since it's a k8s-API-server object, not a GCP one) maps
# to this GCP service account, so app/worker pods get real, short-lived GCP
# credentials for the GCS bucket + Secret Manager without a mounted key
# file. See: https://cloud.google.com/kubernetes-engine/docs/how-to/workload-identity

resource "google_service_account" "app" {
  account_id   = "delta-chat-app-${var.environment}"
  display_name = "delta-chat application workload identity"
}

resource "google_service_account_iam_member" "workload_identity_binding" {
  service_account_id = google_service_account.app.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[delta-chat/delta-chat-app]"
}

resource "google_storage_bucket_iam_member" "app_blob_access" {
  bucket = google_storage_bucket.blobs.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.app.email}"
}

resource "google_secret_manager_secret_iam_member" "app_secret_access" {
  for_each  = google_secret_manager_secret.app_secrets
  secret_id = each.value.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.app.email}"
}

# CI/CD identity (e.g. for k8s/scripts/build-images.sh run from a pipeline)
# — push access to Artifact Registry only, nothing else, so a compromised
# CI credential can't touch data/infra directly.
resource "google_service_account" "ci" {
  account_id   = "delta-chat-ci-${var.environment}"
  display_name = "delta-chat CI/CD (image build + push only)"
}

resource "google_artifact_registry_repository_iam_member" "ci_push" {
  location   = google_artifact_registry_repository.delta_chat.location
  repository = google_artifact_registry_repository.delta_chat.name
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.ci.email}"
}
