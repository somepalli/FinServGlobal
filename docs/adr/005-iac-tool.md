# ADR-005: Infrastructure as code tool

Date: 2026-08-20
Status: Accepted

## Context

The assignment restricts the implementation to open-source data, models and
libraries. My first pass used Terraform out of habit. Terraform 1.6 and later
ship under the Business Source License 1.1, which is source-available, not
OSI open source, and the licensor is now IBM. The Additional Use Grant permits
internal use, so nothing about this demo would breach the licence - but the
constraint I was handed says open source, and BUSL is not that.

## Decision

Use OpenTofu (MPL 2.0, Linux Foundation, also in the CNCF).

## Alternatives considered

- **Terraform 1.5.7.** The last MPL release. Meets the letter of the constraint
  but pins us to a version from mid-2023 with no security backports.
- **Pulumi.** Apache 2.0 core and Python-native, which would fit the rest of the
  stack. Rejected because the state backend most teams use is a paid service,
  and self-hosting it is more moving parts than a four-day demo justifies.
- **AWS CDK.** Apache 2.0, but it binds the IaC layer to one cloud. The
  architecture document argues for portability of the control plane.

## Consequences

- The HCL is unchanged, so nothing about the topology had to be rewritten.
- We pick up state and plan encryption, which matters because state holds KMS
  key ARNs and cluster endpoints.
- Provider ecosystem is shared, so the AWS provider is the same code.
- Cost: the OpenTofu registry lags the HashiCorp one occasionally on brand-new
  provider releases. Not a factor at this scope.
- I am giving up HCP Terraform, Stacks and Sentinel. None were in the design.

## Note

The cloud itself (AWS) is proprietary and paid. The assignment explicitly asks
us to pick AWS, Azure or GCP, so the platform is exempt by construction. The
constraint applies to data, models and libraries - which is exactly why the
tooling on top of the platform has to be checked.
