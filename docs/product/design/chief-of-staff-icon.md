# Chief of Staff Product Icon

- **Status:** Accepted
- **Owner:** Brad
- **Last updated:** 2026-08-06
- **Design phase:** Production-ready vector handoff

## Purpose

This handoff records the accepted product icon for Chief of Staff. The mark
represents a protected briefing field: several trusted signals remain in view
while one meaningful item receives focused attention.

The icon is original to this product. It does not use or imitate the
Northridge Church logo and does not introduce a church, chatbot, automation,
or generic task-management metaphor.

![Chief of Staff product icon](assets/chief-of-staff-icon.svg)

## Asset inventory

| Asset | Role |
| --- | --- |
| [`chief-of-staff-icon.svg`](assets/chief-of-staff-icon.svg) | Authoritative scalable source on a 1024-by-1024 canvas |
| [`chief-of-staff-icon-32.png`](assets/chief-of-staff-icon-32.png) | Browser-grade 32-pixel validation render and raster fallback |
| [`chief-of-staff-icon-16.png`](assets/chief-of-staff-icon-16.png) | Browser-grade 16-pixel validation render and raster fallback |

The SVG is the source of truth. The PNG files are derived validation assets;
they must not be edited independently.

## Visual construction

The mark uses only three exact flat colors:

| Token | Value | Use |
| --- | --- | --- |
| Ink | `#241F20` | Protective frame and ordinary briefing signals |
| Gold | `#F2C659` | One selected signal only |
| Cream | `#EEE7D6` | Quiet square background |

Two substantial ink brackets hold four horizontal briefing signals. The
second signal is gold. The geometry uses strong negative space, rounded ends,
generous outer padding, and no decorative detail.

The mark contains no gradients, shadows, filters, gloss, texture, letters,
initials, wordmark, or external branding. Its simple geometry can also be
translated into a one-color mark when a future medium requires one, but that
translation is not included in this handoff.

## Meaning

- The surrounding brackets represent stewardship and protected attention.
- The ordered fields represent trusted information synthesized into a concise
  briefing.
- The single gold field represents judgment: one signal receives attention
  without making every item urgent.
- The open negative space keeps the mark calm and editorial rather than
  mechanical or dashboard-like.

## Usage rules

- Use the SVG as the primary product-icon source.
- Preserve the square canvas, cream background, geometry, colors, and outer
  padding.
- Do not crop, rotate, distort, outline, recolor, animate, or add effects.
- Do not add the Northridge logo or combine this mark with another symbol.
- When the product name is visible beside the icon, treat the icon as
  decorative. When it appears alone, provide the accessible name
  `Chief of Staff`.
- Use the committed 16-pixel and 32-pixel PNGs only when a raster favicon is
  required; derive any larger raster size from the SVG.

## Favicon validation

The authoritative SVG was rendered through a browser-grade SVG pipeline and
inspected at native favicon sizes.

| Size | Result |
| --- | --- |
| 32 by 32 pixels | Pass: the protective frame, four briefing fields, and gold focus field remain distinct |
| 16 by 16 pixels | Pass: the mark retains a strong bracketed silhouette and visible gold focus; individual field detail compresses appropriately |

The validation renders are opaque and preserve the cream background. Normal
edge antialiasing introduces intermediate raster colors, but the SVG itself
contains only the three authoritative flat colors above.

## Implementation boundary

The accepted icon is integrated into the local web application as its visible
header mark and SVG favicon, with the committed PNGs providing 32-pixel and
16-pixel favicon fallbacks. Byte-identical application copies are packaged
under `src/chief_of_staff/web/static/`; the SVG in this design directory
remains the governing source.

This integration does not change desktop packaging, scheduled-trial behavior,
product behavior, or connector boundaries. Future icon changes must begin with
the governing design asset and preserve the usage rules above.
