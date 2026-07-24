# Managed alternative to k8s/redis/deployment.yaml's self-hosted Redis —
# swap REDIS_URL in the ConfigMap to this instance's host:port for a
# production deployment instead of running Redis as a pod. Not required to
# use both; pick one. BASIC tier (no automatic failover) by default,
# matching this project's actual durability needs (a chat-session cache
# and a Celery broker, not a system of record — that's MongoDB).
resource "google_redis_instance" "cache" {
  name           = "delta-chat-${var.environment}"
  tier           = var.redis_tier
  memory_size_gb = var.redis_memory_size_gb
  region         = var.region

  authorized_network = google_compute_network.vpc.id
  connect_mode       = "PRIVATE_SERVICE_ACCESS"

  redis_version = "REDIS_7_0"

  labels     = var.labels
  depends_on = [google_service_networking_connection.private_vpc_connection]
}
