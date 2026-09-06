---
name: scroll-storytelling
description: Design, build, and verify distinctive accessible scroll-driven websites without a cloned template or external skill runtime.
version: 1.0.0
author: Jonathan Ai
license: MIT
platforms: [linux, macos, windows]
metadata:
  references: [https://github.com/nateherkai/scroll-craft]
  tags: [web-design, scroll, motion, accessibility, verification]
---

# Scroll storytelling

Use this skill when the user wants a cinematic or editorial site whose scroll position controls meaningful visual progress.

## Design contract

1. Read the real brand kit and content first. Never invent statistics, testimonials, dashboards, or claims.
2. Choose one page grammar before coding: continuous world, chaptered editorial, filmic stage, gallery rail, split stage, typographic poster, live surface, or rhythmic cut list.
3. Write a feeling curve with one intended emotion and one visible cause per act. Give one act the engineered peak; adjacent acts may not be filler duplicates.
4. Define one interaction unique to this project. A recolored generic reveal is not a signature.
5. Keep body measure around 45–75 characters, use at most two type families, use a 4px spacing basis, avoid pure black, preserve visible focus, and supply reduced-motion behavior.
6. Treat scroll as a timeline only where progress changes something perceptible. Ordinary reading content remains ordinary document flow.

## Build

- Prefer semantic HTML and CSS custom properties over a configuration-generated page skeleton.
- Keep the engine small: one normalized `--scroll-progress` value, IntersectionObserver for section state, requestAnimationFrame for rendering, and no handler that forces layout every wheel event.
- Pin sparingly. A pinned segment must have a clear entry, progress, exit, keyboard-readable copy, and a static reduced-motion state.
- Encode user-supplied video for browser delivery only after confirming FFmpeg availability. Never require paid asset generation.
- Build mobile composition intentionally; do not merely shrink desktop coordinates.

## Verification gate

Run the project's existing checks, then verify at desktop and mobile widths:

- no horizontal overflow, dead scroll, unreachable copy, stuck media, focus loss, or scroll trap;
- every important line reaches readable opacity and adequate contrast over the brightest and darkest frames behind it;
- reduced motion disables scrubbing/parallax while preserving all content;
- keyboard navigation and landmarks work without the pointer;
- the last act resolves the narrative instead of ending with a generic button grid.

Capture a scroll-position contact sheet or screenshots at the start, transitions, peak, and end. Report any visual judgment that automation cannot prove.
