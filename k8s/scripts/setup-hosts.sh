#!/usr/bin/env bash
# Local-cluster convenience only (kind/minikube): adds an /etc/hosts entry
# so the hostname in k8s/ingress/ingress.yaml resolves to the ingress
# controller's local IP, without needing real DNS. Not relevant for a real
# GKE deployment behind a real domain — there you'd point actual DNS at the
# load balancer IP from `kubectl get ingress` instead of editing /etc/hosts.
#
# Usage: sudo ./setup-hosts.sh [hostname]
set -euo pipefail

HOST="${1:-delta-chat.example.com}"
INGRESS_IP="$(kubectl -n ingress-nginx get svc ingress-nginx-controller \
  -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || true)"

if [ -z "$INGRESS_IP" ]; then
  # kind/minikube typically expose the controller via a NodePort/localhost
  # rather than a real LoadBalancer IP.
  INGRESS_IP="127.0.0.1"
  echo "No LoadBalancer IP found — defaulting to 127.0.0.1 (kind/minikube-style setup)."
fi

if grep -q "$HOST" /etc/hosts; then
  echo "Removing existing /etc/hosts entry for $HOST"
  sed -i.bak "/$HOST/d" /etc/hosts
fi

echo "$INGRESS_IP $HOST" >> /etc/hosts
echo "Added: $INGRESS_IP $HOST"
