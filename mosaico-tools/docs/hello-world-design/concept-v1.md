# GSP Hello World concept design v1

Status: user-approved concept image generated with built-in imagegen. Not a GSP simulator or device screenshot.

Reference: https://mosaico.espressif.com/ (2026-09-19)

Target screen: 480×480; the concept is an enlarged square design.

Visual style: website-inspired warm white background, near-black text and brand orange #FF4C01; large headings, modular geometry and pill buttons.

Proposed interaction: tapping Say hello increments hellos from an initial 00. The counter is not system telemetry. The top modular graphic is decoration, not a menu entry.

The user subsequently approved implementation. The application is consolidated in `projects/hello_world`, using native GSP controls and shared C tap logic; see [implementation and validation](implementation.md).

Concept image: hello-world-concept-v1.png

## Generation prompts

Generated with built-in imagegen; original and revision prompts follow.

### Original prompt

Use case: ui-mockup.
Create ONE beautiful, high-fidelity flat front-facing UI design concept for the ESP-Mosaico Hello World firmware, designed on a 480 by 480 logical pixel square touchscreen. Output a square high-resolution image of just the screen, edge-to-edge, no physical device, no perspective, no presentation border, no surrounding labels.

Art direction is based on the actual official mosaico.espressif.com website: warm off-white paper #F6F6F3, near-black #101010 typography, vivid orange #FF4C01 accent, generous breathing room, Trueno-like clean geometric sans serif, subtle gray fine divider lines, pill-shaped buttons. Confident industrial editorial typography, premium minimal maker product. Faithfully use this light black-and-orange brand system.

Layout using 480x480 coordinates:
- 32px safe padding. Top at y32, small elegant wordmark "ESP-MOSAICO" with "ESP-" black semibold and "MOSAICO" orange regular. Right aligned at the top a small black geometric 2x2 modular square motif with one orange tile; decorative only, no menu icon.
- A very fine light-gray horizontal divider across x32 to448 at y70.
- Main hero on the left, starting y108: giant bold geometric black text in two lines, exactly "Hello," then "World!" (approximately 66px type on logical canvas, close line spacing). Orange small square period-like ornament next to the title, without obscuring text.
- To the right of the hero, x326 to440, y130 to242, a compact playful modular mosaic of 4 rounded square tiles in orange, black, warm gray, and outlined off-white. A quarter-circle cutout and small circle create an abstract friendly composition. Entirely flat vector-like design, precise geometry, no 3D gloss. Leave clear separation from lettering, do not overlap text.
- Below title at x34 y285, two lines of quiet gray supporting text, exactly "Your next idea" and "starts here." in readable approximately 20px regular type.
- At y359, x32, a black pill button 284px wide and 60px high, label "Say hello" in white with an orange simple right arrow at right end. On its right, a separate unobtrusive two-line touch counter with large black "00" and small gray "hellos" underneath, aligned within x353 to435.
- Bottom y451, small gray "HELLO WORLD" at left and "ESP32-S31" at right, 11-12px letterspacing. Keep bottom safe padding.

The screen must feel like an elegant welcome page for a tiny embedded development board, not a website dashboard. Show no wifi, battery, connected indicators, fabricated telemetry, runtime version, gradients, shadows, neon, glass panels, extra cards, or controls. Crisp text, carefully balanced optical spacing, restrained monochrome+orange palette. All text exactly as specified. This is a concept still of the initial state; intended interaction is that each Say hello tap increments the displayed hello count.

### Final revision prompt

Edit this ESP-Mosaico UI concept image. Fix ONLY the missing background and restore text opacity: Composite the entire current design onto a completely SOLID OPAQUE warm off-white #F6F6F3 background filling every pixel of the square canvas. No transparency anywhere, opaque final screenshot, alpha 255 throughout. This is a SCREENSHOT of a device UI with an off-white screen background, not a cutout asset. Preserve all existing layout, positions, typography, black/orange palette, button, tiles and wording. Make all black lettering fully opaque #101010, gray supporting text fully opaque #70706C, keep white button text. The background should be visibly warm light gray as on premium paper. Keep everything else unchanged. Do not remove the background.
