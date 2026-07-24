#!/usr/bin/env bash
# Restarts api/worker/flower to pick up a newly-pushed image tag (after
# build-images.sh) without re-applying every manifest.
#
# Usage: KUBE_CONTEXT=your-real-context ./rollout.sh
set -euo pipefail

CTX="${KUBE_CONTEXT:?Set KUBE_CONTEXT explicitly}"

for deploy in api worker flower; do
  kubectl --context "$CTX" -n delta-chat rollout restart "deployment/$deploy"
done
for deploy in api worker flower; do
  kubectl --context "$CTX" -n delta-chat rollout status "deployment/$deploy" --timeout=180s
done
