---
name: interface-art-direction
description: Define or refine a web or desktop interface's visual direction using explicit layout-variance, motion-intensity, and information-density choices. Use before implementing a new UI or when an existing interface feels generic or inconsistent.
---

# Interface art direction

Turn the product brief and current interface into a small, deliberate visual system before changing code. Preserve the product's established identity unless the user requests a redesign.

## Choose three controls

State each control on a 1–5 scale and explain it in one sentence:

- **Layout variance:** 1 is regular and centered; 5 uses purposeful asymmetry and varied composition.
- **Motion intensity:** 1 is essential state feedback only; 5 uses choreographed transitions and scroll-linked movement.
- **Information density:** 1 favors focused, spacious views; 5 favors compact operational dashboards.

Infer values from audience, task frequency, content volume, platform, and existing design—not from novelty. Let the user override any value. Do not force every page into the same composition; keep typography, spacing, color, and interaction rules coherent while allowing page-specific hierarchy.

## Produce the direction

Define the type scale, spacing rhythm, surface hierarchy, color roles, radius/border treatment, icon approach, responsive behavior, and the few motion patterns the product actually needs. Identify one memorable visual idea tied to the product rather than adding generic gradients, glass, oversized headings, or decorative cards.

For redesigns, inspect the working UI first. Fix the largest hierarchy, readability, responsiveness, and consistency problems before cosmetic details. Reuse working components and tokens where practical.

## Guardrails and verification

Maintain keyboard access, visible focus, contrast, reduced-motion behavior, readable type, sensible hit targets, and usable narrow-screen layouts. Motion must communicate state or spatial continuity and must never block the task.

After implementation, render or run the interface at representative desktop and narrow widths. Verify the primary flow, empty/loading/error states, overflow, focus order, contrast, and reduced motion. Report observable checks and remaining tradeoffs rather than calling the result polished without evidence.
