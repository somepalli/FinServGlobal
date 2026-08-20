# Regulatory Compliance Assistant

<!-- Fill this in last, after the demo recording exists. Order that matters:
     1. what it does, in three sentences
     2. demo recording link + two screenshots
     3. how to run it locally (the commands below, verified)
     4. architecture doc link, ADR index
     5. evaluation results table
     6. known limitations - be specific, this section earns marks -->

## Running locally

    docker compose up -d qdrant postgres
    uv sync --locked
    uv run python -m compliance.ingest.run          # indexes data/corpus
    uv run uvicorn compliance.api.main:app --reload
    pnpm -C apps/web install --frozen-lockfile --ignore-scripts && pnpm -C apps/web dev

## Corpus

Five source documents, listed in `data/corpus/manifest.yaml`. They are not
committed - `uv run python -m compliance.ingest.fetch` downloads them from the
publishing regulators and verifies the SHA-256 recorded in the manifest.

## Layout

    apps/api      FastAPI, retrieval, LangGraph agent, eval harness
    apps/web      Next.js demo UI
    deploy/tofu   OpenTofu - EKS demo topology, ap-south-1
    deploy/helm   Chart for the API, UI and Qdrant
    docs/         Architecture document and ADRs
