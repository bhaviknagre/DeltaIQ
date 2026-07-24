output "gke_cluster_name" {
  value = google_container_cluster.primary.name
}

output "gke_cluster_endpoint" {
  value     = google_container_cluster.primary.endpoint
  sensitive = true
}

output "gke_get_credentials_command" {
  description = "Run this to point kubectl at the new cluster."
  value       = "gcloud container clusters get-credentials ${google_container_cluster.primary.name} --region ${var.region} --project ${var.project_id}"
}

output "artifact_registry_repo" {
  description = "Full path for docker push/pull — matches k8s/scripts/build-images.sh's REPO usage."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.delta_chat.repository_id}"
}

output "redis_host" {
  description = "Memorystore private IP — set REDIS_URL to redis://<this>:<redis_port> in k8s/configmap/configmap.yaml if using this instead of k8s/redis/."
  value       = google_redis_instance.cache.host
}

output "redis_port" {
  value = google_redis_instance.cache.port
}

output "gcs_blob_bucket" {
  description = "Bucket name for a future GCSBlobStore backend (src/storage/blob_store.py)."
  value       = google_storage_bucket.blobs.name
}

output "app_service_account_email" {
  description = "GCP service account for Workload Identity — bind the k8s ServiceAccount 'delta-chat-app' in namespace 'delta-chat' to this."
  value       = google_service_account.app.email
}

output "ci_service_account_email" {
  value = google_service_account.ci.email
}

output "secret_manager_secret_ids" {
  description = "Secret Manager container names — add real values via `gcloud secrets versions add`, see secrets.tf."
  value       = { for k, v in google_secret_manager_secret.app_secrets : k => v.secret_id }
}
