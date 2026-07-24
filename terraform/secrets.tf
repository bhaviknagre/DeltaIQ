# Creates the Secret Manager *containers* only — never a secret value.
# Real values get added out-of-band, after apply, so they never pass
# through a .tf file or land in Terraform state:
#
#   echo -n "gsk_..." | gcloud secrets versions add delta-chat-groq-api-key-dev --data-file=-
#
# (Terraform *can* set a secret's value via google_secret_manager_secret_
# version with a `secret_data` argument — deliberately not used here, since
# that argument's value gets stored in plaintext in the state file, which
# is exactly the kind of leak this project has been careful to avoid with
# .env/.env.example throughout. Container-only + gcloud for the value is
# the safer split.)
locals {
  secret_names = [
    "anthropic-api-key",
    "openai-api-key",
    "groq-api-key",
    "pinecone-api-key",
    "mongodb-uri",
    "minio-access-key",
    "minio-secret-key",
    "langfuse-public-key",
    "langfuse-secret-key",
  ]
}

resource "google_secret_manager_secret" "app_secrets" {
  for_each  = toset(local.secret_names)
  secret_id = "delta-chat-${each.value}-${var.environment}"

  replication {
    auto {}
  }

  labels     = var.labels
  depends_on = [google_project_service.required]
}
