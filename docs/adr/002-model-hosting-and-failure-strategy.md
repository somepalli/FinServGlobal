# ADR-002: Model hosting and failure strategy

Date: 2026-08-21
Status: Accepted

## Context

The system processes RBI-regulated documents and transaction facts that must
remain in the chosen Indian deployment boundary. MiFID II material also carries
data-protection expectations. Hosting and failure handling are one decision: a
fallback that sends regulated text to an out-of-region service defeats the
residency property of the primary model.

## Decision

Run regulated inference through self-hosted vLLM on EKS in `ap-south-1`. The
current deployment uses `Qwen/Qwen2.5-7B-Instruct-AWQ`, selects nodes labelled
`workload: inference`, tolerates the GPU taint, and requests one NVIDIA GPU in
`deploy/helm/values.yaml` and `vllm-deployment.yaml`. `deploy/tofu/main.tf`
creates the matching `g5.xlarge` inference node group in the configured region.

The accepted failure order stays in-region:

1. Use a second replica pool of the same model for capacity.
2. Use a secondary model pool for availability.
3. Use a smaller model for latency and mark the response degraded.
4. Stop model attempts and return retrieved clauses without synthesis.

Only the terminal tier is implemented today. In
`apps/api/src/compliance/retrieval/answer.py`, empty generation or mean citation
support below `min_citation_support` returns `Answer(synthesised=False)` with
retrieved clauses. The transaction graph similarly retries validation once and
then uses `fallback_assessment` with unresolved questions. The Helm release has
one vLLM replica and the OpenTofu inference group has `max_size = 1`; the first
three tiers require additional pools and routing before they can be claimed as
runtime behavior.

The terminal refusal is deliberate. An uncited guess is a worse compliance
failure than an explicit lack of support. This is where I keep deterministic
evidence when generation cannot be trusted.

## Alternatives considered

- **Amazon Bedrock as primary.** Managed capacity would remove GPU operations,
  but model availability and cross-Region inference profiles change over time.
  India is not a geography profile for global routing, so I cannot assume newer
  models remain in Mumbai. It is also a paid managed service, outside the
  open-source prototype constraint.
- **Bedrock as fallback.** Rejected for the same residency reason. Failure is not
  permission to move regulated text outside the selected region.
- **GCP Vertex as another tier.** Rejected because another cloud increases
  identity, networking, and incident-response work and was not in scope.

## Consequences

- The team owns GPU capacity, model upgrades, and inference on-call work.
- At about ten thousand queries per day, the cost comparison with a managed API
  is close. Residency, not price, made the decision; higher sustained volume
  makes self-hosting economics clearer.
- The accepted capacity, availability, and latency tiers are deployment debt.
  Until those pools exist, a vLLM outage reaches the terminal behavior sooner
  than this target order intends.
