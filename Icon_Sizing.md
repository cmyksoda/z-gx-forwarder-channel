# Wii Channel Asset Sizing — 4:3 and 16:9

Reference for authoring channel art that fills the screen in **both** aspect
ratios. Derived from the LSD Dream Emulator and mGBA-GX forwarder builds.

## Why 4:3-sized art gets black side bars in 16:9

The Wii always renders a **640×480 anamorphic framebuffer** and lets the TV
stretch it to 16:9. To stop everything looking horizontally fat, the System Menu
compensates by showing **4/3 more horizontal layout units** in widescreen.

**Height never changes. Only width.**

| | 4:3 shows | 16:9 shows |
|---|---|---|
| icon | 128 × 96 | **170.67** × 96 |
| banner | 608 × 456 | **810.67** × 456 |

Art authored at exactly the 4:3 width fits perfectly in 4:3, but in 16:9 the Menu
reveals ~21 empty layout units either side of the icon and ~101 either side of
the banner. Empty layout renders **black** — those are the bars.

mGBA-GX's icon escapes this by accident: it kept Tantric's original
`BackgroundPic` pane at 256×96 (a scrolling tiled pattern), which over-covers the
widescreen extent. The LSD icon replaced it with exact 128×96 layers, so it bars.

### Evidence for the 4/3 factor

Two independent confirmations, both from the donor/project files:

1. Nintendo's full-bleed panes in the donor banner — `StripePicture` and
   `TitleBarPicture` — are both **exactly 832 wide**. That is 810.67 rounded up
   to the next multiple of 64.
2. `mGBA-GX github-staging/BUILDING.md:217` states the 16:9 splash is the art
   "squashed to **75%** width". 0.75 is precisely the inverse of 4/3 — the same
   constant applied in the opposite direction.

## Authoring sizes

| asset | author at | keep all content inside | notes |
|---|---|---|---|
| **icon** | **176 × 96** | centre **128 × 96** | 24 px bleed each side |
| **banner** | **832 × 456** | centre **608 × 456** | 112 px bleed each side; matches Nintendo's own panes |
| **splash 4:3** | **640 × 480** | — | PNG colortype 2 (RGB, no alpha) |
| **splash 16:9** | compose **854 × 480**, then squash to **640 × 480** | — | colortype 2; the squash cancels the TV stretch |

The side margins are **bleed, not content** — background continuation only.
Anything that must actually be seen has to live inside the centre 4:3 box,
because 4:3 users see nothing outside it.

### It's the pane width that matters, not the canvas

The donor icon declares a `lyt1` canvas of 640×480 yet renders in 128×96 — the
System Menu does not use the canvas to set the viewport. Editing it accomplishes
nothing.

**Widen the background *picture pane* and keep it centred at x=0.**

## The icon byte cap is the real constraint

`icon.bin` has a hard **102,400-byte (0x19000) decompressed** cap. Exceeding it
is a confirmed brick after the Health & Safety screen — the Menu checks 0x19000
and then decompresses into NULL.

Fixed overhead in the LSD `icon.bin` (brlan + brlyt + `Black.tpl` + U8 node table
and strings) is **2,208 B**, leaving **100,192 B** for three fade layers, i.e.
~33,397 B each.

| 3 layers @ | RGB565 | CI8 | CMPR |
|---|---|---|---|
| 172 × 96 | 101,472 ✓ *(0.7 px margin — razor thin)* | ✓ | ✓ |
| **176 × 96** | 103,776 ✗ over by 1,376 | 54,624 ✓ | 27,744 ✓ |
| 192 × 96 | 112,992 ✗ | 59,232 ✓ | 30,048 ✓ |

**A widescreen three-layer icon cannot stay RGB565.** Options:

- **CMPR** (4 bpp, DXT1-style) — cheap enough that width stops mattering.
  *Untested:* only RGB565 icons have shipped so far, so confirm the System Menu's
  TPL loader accepts CMPR in Dolphin before trusting it on hardware.
- **CI8** — safer, but expect banding on gradients.

`Black.tpl` is a 4×4 texture stretched over its pane, so it costs 96 B at any
width.

## Banner size

No verified cap. For reference:

| banner background | decompressed `banner.bin` |
|---|---|
| 608 × 456 RGB565 (LSD, shipped, works) | ~592 KB |
| 832 × 456 RGB565 | ~796 KB — untested territory |
| 832 × 456 CI8 | ~418 KB |
| 832 × 456 CMPR | ~227 KB |

CMPR or CI8 on the background keeps a widescreen banner *below* the size already
proven to work. If certainty is wanted, the banner limit can be found the same
way the icon's 0x19000 check was.

## Known-stale notes elsewhere

`LSD_Forwarder/BUILDING.md:78` states "the icon viewport is 128×96 and the
banner's is 608×456" without qualification, and `build/tools/verify.py` **asserts**
every visible pane matches those numbers. Both are **4:3-only truths** — that
assertion will actively reject correct widescreen art. Fix before reusing that
toolchain.

## Also watch (carried over from prior builds)

`BackgroundMaterial` is not an identity material in either archive. Before
reusing the pane for a full-bleed image, reset **all** of `wrap_s` / `wrap_t` /
`XScale` / `YScale` / `XTrans` / `YTrans` / `Rotate`:

| | banner | icon |
|---|---|---|
| `wrap_s` | `GX_MIRROR` | `GX_REPEAT` |
| `XScale` | **2.0** | 1.0 |
| `XTrans` | 0 (RLTS-animated) | 0.6 (RLTS-animated) |

Match *any* wrap value when rewriting — a rule that only rewrote `GX_REPEAT`
silently missed the banner's `GX_MIRROR`. Inherited pane alpha matters too:
`Logo00Pane` ships `alpha=b4` (180), and pane alpha multiplies down the tree.

---

## Summary

The Wii shows a wider slice of your artwork on a 16:9 TV; anything not painted
into that extra width comes out black. Author **icon at 176×96** and **banner at
832×456**, with everything important still inside the middle **128×96** /
**608×456**. Splashes stay two 640×480 PNGs, the 16:9 one squashed to 75% width.
The only complication is that a wider icon won't fit the 100 KB limit in RGB565,
so switch it to CMPR (test in Dolphin first) or CI8.
