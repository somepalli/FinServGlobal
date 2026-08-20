.PHONY: install lint test sec sbom eval up down

install:
	uv sync --locked
	pnpm -C apps/web install --frozen-lockfile --ignore-scripts

lint:
	uv run ruff check .
	uv run mypy apps/api/src
	pnpm -C apps/web lint

test:
	uv run pytest

sec:
	uv run bandit -q -r apps/api/src
	uv export --format requirements-txt --no-hashes -o /tmp/req.txt && uv run pip-audit -r /tmp/req.txt
	pnpm -C apps/web audit --audit-level=high
	osv-scanner scan source -r .
	gitleaks detect --no-banner --redact

sbom:
	syft dir:. -o cyclonedx-json=sbom.json
	grype sbom:sbom.json --fail-on high

eval:
	uv run python -m compliance.eval.run --suite ci

up:
	docker compose up -d qdrant
down:
	docker compose down -v
