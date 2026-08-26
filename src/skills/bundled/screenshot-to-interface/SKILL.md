---
name: screenshot-to-interface
description: Convert an attached screenshot, mockup, or design image into working interface code, then render and visually verify it. Use when a user asks to reproduce, rebuild, or modify a UI from an image; supports the project's existing web or desktop stack without requiring a separate screenshot-to-code service.
---

# Screenshot to interface

Treat the attached image as visual evidence, not as a complete specification. Inspect the actual pixels and acknowledge the source image before writing code. Identify the target stack from the project; preserve its framework, component conventions, design tokens, routing, accessibility patterns, and package manager unless the user explicitly requests a new stack.

## Reconstruct deliberately

1. Inventory the visible layout regions, hierarchy, typography, spacing, colors, borders, radii, icons, images, interactive states, and responsive clues.
2. Separate reusable components from page-specific composition. Reuse repository assets and existing components when provenance and fit are clear; do not invent third-party logos or copy inaccessible proprietary assets.
3. Implement semantic structure and real controls before cosmetic matching. Include keyboard behavior, labels, focus, contrast, loading, empty, and error states implied by the product flow.
4. Match the reference through project-owned tokens and maintainable CSS. Avoid absolute-positioning the whole screenshot, embedding the source image as the UI, or producing a nonfunctional visual shell.
5. If the screenshot leaves behavior ambiguous, choose the smallest conventional behavior consistent with the project and state the assumption.

## Render-and-compare loop

Run the narrowest viable development or preview command. Render the result at the screenshot's approximate viewport and at one narrow viewport, using the project's browser or screenshot tooling when available. Compare large geometry first, then typography, spacing, color, and detail. Fix observable discrepancies in bounded passes; do not claim pixel accuracy without a rendered comparison.

Preserve user data and existing behavior. Run relevant tests and a production build when practical. Return the implemented files, preview or rendered artifact, verification evidence, known differences, and downloadable package requested by the user.

## Image and privacy boundaries

Keep uploaded images within the current project/session unless the user approves an external service. Prefer configured local or existing vision providers. Never silently upload a confidential screenshot, expose embedded credentials or personal data, or add a paid model/runtime dependency merely to complete this workflow.
