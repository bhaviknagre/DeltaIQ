resource "google_container_cluster" "primary" {
  name     = "${var.gke_cluster_name}-${var.environment}"
  location = var.region # regional cluster (control plane replicated across zones), not zonal

  network    = google_compute_network.vpc.id
  subnetwork = google_compute_subnetwork.gke.id

  # Manage node pools separately (google_container_node_pool below) instead
  # of the cluster's built-in default pool — lets the node pool be resized/
  # replaced without recreating the whole cluster.
  remove_default_node_pool = true
  initial_node_count       = 1

  ip_allocation_policy {
    cluster_secondary_range_name  = "pods"
    services_secondary_range_name = "services"
  }

  # Workload Identity: lets k8s ServiceAccounts assume real GCP IAM
  # identities directly (no long-lived JSON key files mounted into pods) —
  # what iam.tf's workload-identity binding for the GCS bucket relies on.
  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }

  release_channel {
    channel = "REGULAR"
  }

  deletion_protection = false # set true before using this for anything real

  depends_on = [google_project_service.required]
}

resource "google_container_node_pool" "primary" {
  name     = "${var.gke_cluster_name}-${var.environment}-pool"
  location = var.region
  cluster  = google_container_cluster.primary.name

  initial_node_count = var.gke_node_count

  autoscaling {
    min_node_count = var.gke_min_node_count
    max_node_count = var.gke_max_node_count
  }

  node_config {
    machine_type = var.gke_machine_type
    disk_size_gb = 50
    disk_type    = "pd-standard"

    oauth_scopes = ["https://www.googleapis.com/auth/cloud-platform"]

    workload_metadata_config {
      mode = "GKE_METADATA" # required for Workload Identity on the node
    }

    labels = var.labels
    tags   = ["delta-chat", var.environment]
  }

  management {
    auto_repair  = true
    auto_upgrade = true
  }
}
