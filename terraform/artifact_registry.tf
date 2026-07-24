resource "google_artifact_registry_repository" "delta_chat" {
  location      = var.region
  repository_id = "delta-chat"
  description   = "Docker images for delta-chat (single image reused for api/worker/flower — see k8s/api/deployment.yaml)"
  format        = "DOCKER"

  labels     = var.labels
  depends_on = [google_project_service.required]
}
