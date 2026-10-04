# ADR 0001: Platform architecture and state boundaries

- **Status:** Accepted
- **Date:** 2026-10-04

## Context

Lumen must support horizontally scaled API pods, asynchronous document ingestion, hybrid retrieval, streaming answers, and local development without a paid dependency. Query serving must remain isolated from expensive or bursty ingestion work.

## Decision

- Use FastAPI with Python 3.12 for a stateless HTTP/SSE API and Celery workers for asynchronous ingestion.
- Use PostgreSQL as the durable system of record, with pgvector HNSW for vector search and PostgreSQL full-text search for lexical retrieval.
- Use Redis for broker/queue coordination, rate limits, cache, and short-lived coalescing state; Redis is not the durable source of truth.
- Store original files in an S3-compatible object store. Local development uses a compatible local service; deployment can use Cloudflare R2 where its current plan and quotas fit.
- Deploy query and ingestion worker pools separately so their concurrency, resource limits, and scaling policies do not contend.
- Keep service contracts provider-neutral where practical; production choices must be validated against current free-tier limits before deployment.

## Consequences

PostgreSQL availability and capacity are central to correctness and retrieval latency. Queue delivery is treated as at-least-once, so ingestion operations must be idempotent and poison jobs must be observable and dead-lettered. Local object storage can validate the S3 API path without tying development to external credentials.

## Alternatives considered

- Synchronous ingestion in API requests: rejected because file parsing and embedding create unbounded request latency and resource contention.
- Redis as primary persistence: rejected because queue/cache eviction must not lose document or identity state.
- Managed paid database or model APIs as hard dependencies: rejected because they violate the cost constraint and reduce portability.
