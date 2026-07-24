resource "google_compute_network" "vpc" {
  name                    = "delta-chat-${var.environment}"
  auto_create_subnetworks = false
  depends_on              = [google_project_service.required]
}

resource "google_compute_subnetwork" "gke" {
  name          = "delta-chat-gke-${var.environment}"
  ip_cidr_range = "10.10.0.0/20"
  region        = var.region
  network       = google_compute_network.vpc.id

  # Secondary ranges required for GKE's VPC-native (alias IP) networking —
  # separate address space for pods vs. services so they don't collide with
  # node IPs or each other.
  secondary_ip_range {
    range_name    = "pods"
    ip_cidr_range = "10.20.0.0/14"
  }
  secondary_ip_range {
    range_name    = "services"
    ip_cidr_range = "10.30.0.0/20"
  }
}

# Memorystore (Redis) needs a dedicated /29 allocated from the VPC via VPC
# peering to Google's managed services network — this is that allocation,
# not a subnet you'd put compute in yourself.
resource "google_compute_global_address" "private_service_range" {
  name          = "delta-chat-private-services-${var.environment}"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = google_compute_network.vpc.id
}

resource "google_service_networking_connection" "private_vpc_connection" {
  network                 = google_compute_network.vpc.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_service_range.name]
}

# Allow intra-cluster traffic (pod-to-pod, pod-to-service) — GKE manages
# most of this itself, but an explicit allow rule for the VPC's own ranges
# avoids surprises if a stricter default-deny org policy is in place.
resource "google_compute_firewall" "internal" {
  name    = "delta-chat-allow-internal-${var.environment}"
  network = google_compute_network.vpc.id

  allow {
    protocol = "tcp"
    ports    = ["0-65535"]
  }
  allow {
    protocol = "udp"
    ports    = ["0-65535"]
  }
  allow {
    protocol = "icmp"
  }

  source_ranges = [
    google_compute_subnetwork.gke.ip_cidr_range,
    "10.20.0.0/14",
    "10.30.0.0/20",
  ]
}
