# ADR 0003: Model routing, retrieval, and answer grounding

- **Status:** Accepted
- **Date:** 2026-10-04

## Context

Answer generation depends on external or local models with varying availability, latency, quotas, and free-tier terms. Answers must be grounded in authorized retrieved passages and remain useful when all generation providers fail.

## Decision

- Route generation through LiteLLM with configurable provider adapters, explicit request timeouts, bounded retries, a circuit breaker, and a configurable fallback chain.
- Support Ollama for local development; do not assume any hosted free model has stable capacity or a particular SLA.
- Use FastEmbed BGE-small embeddings and a BGE reranker; batch ingestion embeddings and bound query reranking to the top 50 candidates and top 8 context chunks.
- Combine vector and lexical retrieval with reciprocal-rank fusion. Construct all candidates only after tenant and document authorization predicates have been applied in SQL.
- Keep retrieved passages as untrusted data, separate them from system instructions, sanitize content, validate citations against supplied chunk IDs, and refuse unsupported claims.
- When generation is unavailable, return a clearly labeled retrieval-only response with source passages rather than a fabricated answer.
- Emit LLM traces through Langfuse behind a configurable integration; avoid transmitting secrets or unnecessary PII.

## Consequences

Provider selection, rate limits, model terms, and supported structured-output behavior must be rechecked before deployment. Evaluation must measure retrieval and groundedness independently of a specific provider. Provider outages must not block search results.

## Alternatives considered

- A single model provider: rejected due to quota and availability risk.
- Unrestricted model retries: rejected because retries can amplify overload and violate latency budgets.
- Trusting model-generated citations without validation: rejected because citation IDs must map to authorized retrieved chunks.
