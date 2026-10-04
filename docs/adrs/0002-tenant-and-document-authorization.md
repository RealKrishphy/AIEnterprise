# ADR 0002: Tenant and document authorization boundaries

- **Status:** Accepted
- **Date:** 2026-10-04

## Context

Every persisted business object and every retrieval result must be scoped to a tenant. Document-level ACLs must be enforced before candidate content reaches reranking, prompts, caches, or clients. Application bugs must not turn a missing tenant predicate into cross-tenant access.

## Decision

- Persist `tenant_id` on every tenant-owned row and include it in relevant unique constraints and indexes.
- Enable PostgreSQL RLS on tenant-owned tables. Set tenant identity transaction-locally from authenticated, verified request context; never trust a client-supplied tenant ID as authorization.
- Keep explicit tenant and document ACL predicates in application retrieval SQL in addition to RLS.
- Restrict connection roles and transaction lifetimes to avoid tenant context leaking through pooled connections.
- Make cache keys tenant- and authorization-scope-aware; do not cache data that cannot be safely partitioned by its full authorization context.
- Record security-sensitive mutations and administrative actions in an append-only audit trail.

## Consequences

RLS policies, role configuration, connection pooling, background-task identity, and migrations require integration tests. Worker jobs must carry a validated tenant identity and execute under the same isolation rules. RLS is defense in depth, not a substitute for explicit retrieval authorization.

## Alternatives considered

- Relying only on ORM filters: rejected because raw SQL or future code paths could bypass them.
- Relying only on RLS: rejected because explicit query predicates improve clarity and ensure ACL filtering occurs as part of candidate selection.
