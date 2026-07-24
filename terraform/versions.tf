terraform {
  required_version = ">= 1.5"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.40"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 5.40"
    }
  }

  # No remote backend configured on purpose — this project is "create the
  # IaC, don't deploy" (see repo README-equivalent context). Local state is
  # fine for that. Before any real `terraform apply` against a shared/team
  # GCP project, uncomment and point this at a real, already-existing GCS
  # bucket (state buckets can't be created by the same config that uses
  # them as a backend — chicken-and-egg, needs to exist first):
  #
  # backend "gcs" {
  #   bucket = "REPLACE_ME-tfstate"
  #   prefix = "delta-chat"
  # }
}
