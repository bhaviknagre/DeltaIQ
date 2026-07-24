variable "project_id" {
  description = "GCP project ID to provision into. No default on purpose — must be set explicitly (terraform.tfvars, -var, or TF_VAR_project_id) so a plan/apply can never accidentally target the wrong project."
  type        = string
}

variable "region" {
  description = "Primary GCP region."
  type        = string
  default     = "us-central1"
}

variable "zone" {
  description = "Primary GCP zone (for zonal resources, if any)."
  type        = string
  default     = "us-central1-a"
}

variable "environment" {
  description = "Environment name, used as a resource-name/label suffix (dev/staging/prod)."
  type        = string
  default     = "dev"
}

variable "gke_cluster_name" {
  description = "GKE cluster name."
  type        = string
  default     = "delta-chat"
}

# --- GKE node pool sizing ---
# Small, cost-conscious defaults matching this project's actual resource
# requests in k8s/*/deployment.yaml, not a generically "safe-looking" large
# default. Bump these if you're actually running this for real traffic.
variable "gke_node_count" {
  description = "Initial node count per zone in the primary node pool."
  type        = number
  default     = 2
}

variable "gke_machine_type" {
  description = "Machine type for the primary node pool."
  type        = string
  default     = "e2-standard-4"
}

variable "gke_min_node_count" {
  description = "Cluster autoscaler minimum nodes per zone."
  type        = number
  default     = 1
}

variable "gke_max_node_count" {
  description = "Cluster autoscaler maximum nodes per zone."
  type        = number
  default     = 5
}

# --- Memorystore (Redis) ---
variable "redis_tier" {
  description = "Memorystore service tier: BASIC (no HA/replica) or STANDARD_HA."
  type        = string
  default     = "BASIC"
}

variable "redis_memory_size_gb" {
  description = "Memorystore instance size in GB."
  type        = number
  default     = 1
}

# --- GCS (blob store — MinIO-equivalent in the cloud) ---
variable "gcs_bucket_location" {
  description = "GCS bucket location (can be a region or a multi-region like US)."
  type        = string
  default     = "US"
}

variable "gcs_force_destroy" {
  description = "Allow `terraform destroy` to delete the bucket even if it still has objects. False by default — deliberately requires an explicit override, since this bucket holds source PDFs/OCR artifacts/markup outputs."
  type        = bool
  default     = false
}

# --- Labels applied to every resource that supports them ---
variable "labels" {
  description = "Common resource labels."
  type        = map(string)
  default = {
    project    = "delta-chat"
    managed-by = "terraform"
  }
}
