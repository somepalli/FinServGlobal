# ADR-004: Model gateway selection and supply-chain controls

Date: 2026-08-21
Status: Accepted

## Context

In March 2026, compromised LiteLLM PyPI credentials were used to publish
backdoored versions `1.82.7` and `1.82.8`. One payload used a `.pth` file, which
Python executes during interpreter startup without an application importing
LiteLLM. The maintainers reported that the proxy container images were not
affected and removed the packages ([incident record](https://github.com/BerriAI/litellm/issues/24518)).

LiteLLM has also been exposed to gateway-layer defects, including the
Starlette host-header authentication bypass tracked as CVE-2026-48710. A model
gateway sees every model request and holds provider credentials, so its artifact
integrity is part of the guardrail surface.

## Decision

Use LiteLLM as the model gateway only as an official proxy container mirrored to
the private registry and selected by an immutable digest. Do not install the
`litellm` Python package in the API environment. A release update requires a new
digest, vulnerability review, and deployment change.

This gateway is an accepted target, not current runtime behavior. No LiteLLM
image or Deployment exists in `deploy/helm`, and the API currently calls vLLM's
OpenAI-compatible endpoint directly. The Helm work must add the mirrored image
and network path before this decision is implemented.

Existing controls that will apply to that work are:

- `python-security` checks the uv lock, runs Bandit, exports locked production
  dependencies, and runs `pip-audit`.
- `supply-chain` runs OSV Scanner and Gitleaks. `osv-scanner.toml` contains
  time-bounded, reasoned exceptions rather than blanket suppression.
- `licenses` rejects listed non-open-source Python and Node licenses.
- `image` builds the API, emits a CycloneDX SBOM, blocks high-severity findings,
  signs the resulting digest, and pushes to immutable ECR repositories.

`apps/api/Dockerfile` runs as UID 10001, but its base images currently use tags,
not digests. The gateway image itself is not yet built or scanned by the `image`
job. These are implementation gaps, not controls I can claim today.

## Alternatives considered

- **Bifrost.** A Go binary avoids Python interpreter-startup behavior and has a
  smaller dependency footprint. I rejected it because its ecosystem and budget
  and virtual-key features are less mature. Microsecond routing overhead is not
  decisive when generation takes seconds.
- **OpenRouter, Cloudflare AI Gateway, or Vercel AI Gateway.** None provides the
  self-hosted, in-region path required by ADR-002; they route through third-party
  services.
- **Portkey.** Its open-source core is viable, but more capable guardrail and
  observability features sit in a paid tier. Closed implementation at that
  control point conflicts with the transparency goal.

## Consequences

- Digest pins do not receive security fixes automatically. Someone must monitor
  releases, review advisories, mirror a replacement, and update the deployment.
- Container isolation reduces exposure to the compromised PyPI path; it does not
  make the gateway trusted. Image scanning, signing, runtime isolation, and
  gateway-specific tests remain necessary.
- Adding a gateway creates another service and failure boundary between the API
  and vLLM. It also centralizes routing and credentials so those controls do not
  spread through application code.
