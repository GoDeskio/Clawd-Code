---
name: react-performance-review
description: Diagnose and improve React application performance using measured evidence. Use for slow routes, interaction lag, excessive rerenders, large client bundles, request waterfalls, or performance-focused code review; not for ordinary styling or framework migrations.
---

# React performance review

Find the dominant user-visible bottleneck before changing code. Preserve behavior, accessibility, framework conventions, and the project's supported React version.

## Establish evidence

Identify the affected route and interaction. Use the project's existing profiler, browser trace, bundle analyzer, build output, tests, or reproducible timings where available. If measurement tooling is absent, state the concrete code-path evidence and avoid invented percentages.

Review in this priority order:

1. **Request waterfalls:** start independent work together, move reads to the nearest useful boundary, and avoid serial client fetches that the server can resolve safely.
2. **Client JavaScript:** keep server-only work out of the browser, split genuinely optional heavy features, and avoid pulling entire libraries for one small operation.
3. **Rendering boundaries:** keep state local, avoid broad context updates, stabilize only identities that cause observed work, and compute derived values during render instead of synchronizing duplicate state.
4. **Expensive work:** remove repeated parsing, sorting, serialization, layout measurement, or rendering from hot paths; use caching only when ownership and invalidation are clear.
5. **Loading experience:** stream or reveal useful content at stable boundaries without layout jumps, broken focus, or hidden errors.

Do not add memoization everywhere, suppress dependency warnings, replace accessible elements with faster-looking imitations, or trade correctness for a synthetic benchmark.

## Verify

Run the narrowest relevant tests and the production build. Re-measure the same route or interaction when possible. Report the evidence, the code change, the observed result, and any remaining bottleneck. Distinguish a measured improvement from a reasoned expectation.
