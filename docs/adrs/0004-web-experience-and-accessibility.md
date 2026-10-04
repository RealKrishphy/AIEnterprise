# ADR 0004: Progressive web experience and 3D performance

- **Status:** Accepted
- **Date:** 2026-10-04

## Context

The landing page calls for an immersive scroll-driven 3D story, while the application must remain usable on low-end devices, with reduced motion, and before the 3D payload loads.

## Decision

- Build the application with Next.js App Router and TypeScript; keep core navigation and chat usable without WebGL.
- Implement the storytelling canvas as a lazy-loaded enhancement with a static poster fallback and `prefers-reduced-motion` behavior.
- Use one persistent React Three Fiber canvas for the landing narrative. Prefer instanced meshes and point rendering, adaptive DPR, and explicit resource cleanup.
- Keep the initial JavaScript budget below 250 KB before the deferred 3D chunk; monitor LCP, CLS, and Lighthouse performance as release criteria.
- Ensure keyboard-operable controls, visible focus, semantic content, and non-motion equivalents for scroll-triggered scenes.

## Consequences

3D content must not block core content or interaction. Browser/device-specific performance must be measured; performance targets cannot be inferred from a development machine.

## Alternatives considered

- Rendering each particle as an independent scene object: rejected because draw-call and memory costs grow with scene complexity.
- Making WebGL mandatory: rejected because it excludes unsupported, low-power, and motion-sensitive users.
