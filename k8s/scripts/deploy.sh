#!/usr/bin/env bash
# Applies every manifest in dependency order. Does NOT create
# delta-chat-secrets — that's deliberately a separate, manual step (see
# k8s/secrets/secrets.yaml's header comment) so real credentials never sit
# in a YAML file, committed or not.
#
# Usage: KUBE_CONTEXT=your-real-context ./deploy.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CTX="${KUBE_CONTEXT:?Set KUBE_CONTEXT explicitly — refusing to apply against whatever kubectl's current-context happens to be}"

kubectl --context "$CTX" apply -f "$REPO_ROOT/k8s/namespace.yaml"

echo "== Checking for delta-chat-secrets =="
if ! kubectl --context "$CTX" -n delta-chat get secret delta-chat-secrets >/dev/null 2>&1; then
  echo "delta-chat-secrets not found. Create it first — see k8s/secrets/secrets.yaml"
  echo "for the kubectl create secret command with real values. Aborting."
  exit 1
fi

kubectl --context "$CTX" apply -f "$REPO_ROOT/k8s/configmap/configmap.yaml"

echo "== Generating Grafana ConfigMaps from the repo's source-of-truth provisioning files =="
kubectl --context "$CTX" -n delta-chat create configmap grafana-datasources \
  --from-file="$REPO_ROOT/grafana/provisioning/datasources/prometheus.yml" \
  --dry-run=client -o yaml | kubectl --context "$CTX" apply -f -
kubectl --context "$CTX" -n delta-chat create configmap grafana-dashboards \
  --from-file="$REPO_ROOT/grafana/provisioning/dashboards/delta-chat.json" \
  --dry-run=client -o yaml | kubectl --context "$CTX" apply -f -

for dir in redis minio chroma api worker flower monitoring ingress; do
  echo "== Applying k8s/$dir =="
  kubectl --context "$CTX" apply -f "$REPO_ROOT/k8s/$dir/"
done

echo "== Waiting for api rollout =="
kubectl --context "$CTX" -n delta-chat rollout status deployment/api --timeout=180s
