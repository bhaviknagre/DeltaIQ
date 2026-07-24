# Deployment: Kubernetes & Terraform

!!! warning "Creation-only, not deployed"
    Both the Kubernetes manifests and the Terraform IaC below have been
    written and validated **offline** — schema-validated manifests, a
    `terraform init`'d provider cache. Neither has been applied to a live
    cluster or a real GCP project. Treat this section as "the IaC exists and
    is checked in," not "this is running somewhere."

## Kubernetes (`k8s/`)

| Component | What's there |
|---|---|
| `namespace.yaml` | Namespace `delta-chat` |
| `api/` | Deployment (2 replicas, readiness/liveness on `/`, Prometheus scrape annotations), `hpa.yaml` (CPU 70% + memory 80%, 2–8 replicas), `service.yaml` (80→8000) |
| `worker/` | Deployment (Celery worker, `celery inspect ping` liveness probe), `hpa.yaml` (CPU-only, 2–10 replicas — **the applied default**), `keda-scaledobject.yaml` (scales on Redis list length — a real, ready-to-use alternative, **not installed by default**; requires the KEDA operator and removing the HPA first) |
| `redis/`, `chroma/`, `minio/` | 1-replica Deployments with PVCs (1Gi / 5Gi / 10Gi), MinIO credentials via `secretKeyRef` |
| `monitoring/` | Prometheus (10Gi PVC) + Grafana (2Gi PVC) — dashboards/datasources are generated into ConfigMaps by `deploy.sh`, not duplicated in-repo |
| `flower/` | Deployment + service at `:5555` |
| `configmap/configmap.yaml` | Non-secret env vars mirroring `.env.example`, but pointed at in-cluster DNS (`redis.delta-chat.svc.cluster.local`, etc.), with `RETRIEVAL_BACKEND=hybrid`, `METADATA_STORE=mongo`, `BLOB_STORE=minio` as the production defaults |
| `secrets/secrets.yaml` | **Template only** — every value is `REPLACE_ME`; the header instructs creating the real secret imperatively (`kubectl create secret generic ...`), not by applying this file |
| `ingress/ingress.yaml` | nginx ingress: `/` → api, `/grafana` → Grafana, `/flower` → Flower, `/prometheus` → Prometheus; body-size annotation sized for PDF uploads |

`k8s/scripts/`: `deploy.sh` (applies manifests in order; refuses to run if
`delta-chat-secrets` doesn't exist yet), `build-images.sh` (builds/pushes to
GCP Artifact Registry), `rollout.sh` (restarts api/worker/flower), and
`setup-hosts.sh` (local kind/minikube convenience only).

### Validation

`scripts/checks/check_k8s.py` (`make check-k8s`) validates every manifest
under `k8s/**/*.yaml` **offline** with `kubeconform` — schema-based, never
`kubectl apply`, never talks to a real cluster (includes the KEDA CRD via the
community CRDs-catalog schema). It also asserts `secrets.yaml` contains only
`REPLACE_ME` placeholders — including a check for real-key-shaped strings
like `sk-ant-` / `gsk_` — and spot-checks that MinIO/Grafana deployments pull
credentials via `secretKeyRef`, not inline.

## Terraform / GCP (`terraform/`)

| File | Provisions |
|---|---|
| `apis.tf` | Enables the GCP APIs the rest of the config needs (GKE, Artifact Registry, Redis, Storage, Secret Manager, Compute, IAM, Monitoring, Logging) |
| `gke.tf` | Regional GKE cluster, Workload Identity enabled, autoscaling node pool (`e2-standard-4` default) |
| `artifact_registry.tf` | Docker-format Artifact Registry repo — one image reused across api/worker/flower |
| `iam.tf` | App service account (Workload Identity → k8s SA `delta-chat/delta-chat-app`; Storage objectAdmin + Secret Manager accessor), plus a narrower CI service account (Artifact Registry writer only) |
| `network.tf` | Custom VPC, GKE subnet with pod/service secondary ranges, private-service-access peering for Memorystore, internal firewall rule |
| `redis.tf` | Memorystore instance (`BASIC` tier default, `REDIS_7_0`, private service access) |
| `secrets.tf` | Secret Manager **containers only** for 9 named secrets (LLM provider keys, MongoDB URI, MinIO keys, Langfuse keys) — deliberately no values, to avoid plaintext ever landing in `.tfstate` |
| `storage.tf` | Versioned GCS bucket for blob storage, 90-day noncurrent-version lifecycle rule |
| `variables.tf` | `project_id` has no default (must be set explicitly); other defaults are small/cost-conscious, matching the k8s resource requests |
| `outputs.tf` | Cluster name/endpoint, the `gcloud container clusters get-credentials` command, Artifact Registry path, Redis host/port, bucket name, service account emails, secret IDs |

**No remote state backend is configured** — `versions.tf` states directly
that this is intentional for a "create the IaC, don't deploy" scope, with a
commented-out `backend "gcs"` block left for when it's actually applied.
There is no `.tfstate` file anywhere in the repo; `terraform/.terraform/`
only holds the provider cache from `terraform init`.

```bash
cp terraform/terraform.tfvars.example terraform/terraform.tfvars
# fill in project_id, then:
cd terraform && terraform init && terraform plan
```

`terraform plan` (not `apply`) is the honest way to verify this against a
real GCP project without provisioning anything.
