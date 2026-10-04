# Initial threat model

## Scope and security objectives

Protect tenant data, credentials, uploaded documents, and generated answers against unauthorized access, tampering, and cross-tenant leakage. Preserve integrity of ingestion and audit records, and keep query and ingestion services available under abuse and provider failures.

## Trust boundaries and assets

```text
Untrusted browser/user
  -> CDN/WAF -> stateless API -> PostgreSQL (RLS), Redis, object storage
                              -> LiteLLM/providers
Redis broker -> isolated ingestion workers -> parser / embedding model -> PostgreSQL
```

Assets include identity and refresh tokens, document bytes and extracted text, embeddings, ACLs, prompts and model responses, provider credentials, audit events, and tenant-specific cache entries.

## Principal threats and required controls

| Threat | Required control |
|---|---|
| Cross-tenant reads through a missing filter or pooled DB session | RLS, transaction-local tenant context, explicit tenant predicates, connection-pool integration tests |
| Unauthorized chunks entering prompts or results | ACL joins/filters in retrieval SQL before reranking, tenant-aware caches, citation validation |
| Malicious uploads, parser exploits, or resource exhaustion | File size/type validation, malware scanning where available, isolated bounded workers, parser timeouts, decompression limits, retries and dead-lettering |
| Prompt injection embedded in retrieved documents | Treat passages as untrusted data, isolate instructions, sanitize/limit input, validate output and citations |
| Credential theft or replay | Argon2 password hashes, short-lived access tokens, rotating/revocable refresh tokens, OIDC state/nonce validation, secret management |
| Brute force, scraping, and denial of service | Per-user/tenant token buckets, request/body limits, bounded concurrency, backpressure with `429` and `Retry-After`, edge WAF |
| Cache or queue data crossing security scopes | Tenant/ACL-derived cache keys, restricted Redis network/credentials, bounded TTLs, no authorization decisions from cache alone |
| Sensitive data exposure through telemetry | Redaction, least-privilege access and retention, no secrets in logs, configurable PII handling |
| Privileged changes without accountability | Append-only audit events for authentication, authorization, admin, and document-access policy changes |

## Residual risks and follow-up

Provider free tiers may retain prompts or impose changing quotas; use only approved configurations and minimize transmitted data. Malware scanning, parser sandbox strength, backup/restore, key rotation, retention, and incident response require environment-specific validation. Phase 1 will define concrete roles and policies; later phases will add abuse controls, telemetry redaction, and operational procedures. This initial model is not a substitute for a deployment-specific review or ASVS L2 verification.
