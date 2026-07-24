#!/usr/bin/env bash
# Builds the single project image (same one docker-compose.yml uses for
# delta-chat/chat/eval/ui/celery-worker/flower — only the container command
# differs) and pushes it to GCP Artifact Registry.
#
# Usage: PROJECT_ID=my-gcp-project REGION=us-central1 ./build-images.sh [tag]
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?Set PROJECT_ID (see terraform/variables.tf project_id)}"
REGION="${REGION:-us-central1}"
REPO="${REPO:-delta-chat}"
TAG="${1:-$(git rev-parse --short HEAD)}"

IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/delta-chat:${TAG}"

echo "Building ${IMAGE}"
docker build -t "${IMAGE}" -f ../../Dockerfile ../..
echo "Pushing ${IMAGE}"
docker push "${IMAGE}"
echo ""
echo "Now update k8s/api/deployment.yaml, k8s/worker/deployment.yaml, and"
echo "k8s/flower/deployment.yaml's 'image:' field to: ${IMAGE}"
