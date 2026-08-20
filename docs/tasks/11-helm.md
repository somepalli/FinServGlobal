# Task 11 — Helm templates

## Build
`deploy/helm/templates/` — Deployment, Service and ServiceAccount for the API
and web; StatefulSet with a gp3 PVC for Qdrant; a GPU Deployment for vLLM using
the nodeSelector and tolerations already in values.yaml; Ingress via the AWS
Load Balancer Controller; a Job for ingestion; NetworkPolicy denying egress
from the API except to Qdrant, Postgres and vLLM.

Images referenced by digest, never tag.

## Acceptance
- `helm template deploy/helm` renders with no errors.
- `helm lint` clean.
- The NetworkPolicy is the concrete implementation of "no regulated data leaves
  to external providers" — reference it from the architecture document.
