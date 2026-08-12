"""Regenerate the channel's spiral background at an arbitrary square size.

Why this exists
---------------
The spiral has to spin, and on the Wii a pane rotates about its own centre.
A pane only the size of the viewport would sweep its corners inside the frame
and show black wedges, so the rotating pane must be a square whose *inscribed*
circle covers the viewport: side >= hypot(width, height).

    banner viewport 832 x 456  ->  diagonal 948.8  ->  960 x 960 pane
    icon viewport   176 x  96  ->  diagonal 200.5  ->  208 x 208 pane

`bg.png` (832x456) and `icon_bg.png` (176x96) cannot be resized into those
squares without distorting the rings, so the spiral is re-rendered instead.
The parameters below were *fitted to Jaxi's own art*, not invented:

    pitch 10.0 px, 50% duty, quarter-pitch phase, centred on the exact image
    centre,  s = (r - pitch * theta / 2pi + 2.5) mod pitch    (theta = atan2(dy, dx))

Fitted independently to bg.png and icon_bg.png, both landed on the same pitch
and the same phase, and reproduce the source art to a mean per-channel error of
0.20/255 -- an effectively exact match, so the regenerated square really is
Jaxi's spiral and not a lookalike. `verify_against` re-checks that at build
time. Because both sources share the 10 px pitch, one generator serves the icon
and the banner, and they match each other on screen at 1:1 texel-to-layout-unit
scale.
"""

import numpy as np
from PIL import Image

PITCH = 10.0                       # ring-pair period in pixels, measured from bg.png
DUTY = 0.5                         # equal light/dark bands
PHASE = 2.5                        # quarter pitch; fitted, identical in both sources
LIGHT = (245, 215, 162)            # 40.05% of bg.png
DARK = (245, 190, 90)              # 40.15% of bg.png
SS = 4                             # supersampling factor, recreates the source's AA


def render(size, pitch=PITCH, phase=PHASE, ss=SS, levels=None, xscale=1.0):
    """Return an RGB Image of `size` (w, h) holding the spiral, centred.

    The centre is placed at the exact geometric centre -- ((w-1)/2, (h-1)/2) in
    pixel-centre coordinates -- which is where it sits in both source images.

    `levels` caps the number of distinct antialiasing steps, and so the number
    of distinct colours: the result uses at most `levels + 1`. Passing 15 keeps
    the whole image inside a 16-entry palette, which is what lets it be stored
    as CI4 -- 4 bits per pixel with every colour kept -- and makes a 960x960
    rotating background affordable (460,800 bytes against 1.8 MB of RGBA8).

    `xscale` horizontally compresses the spiral about the centre, turning the
    rings into ellipses. Used for the 16:9 splash: the Wii stretches a 640x480
    framebuffer across a widescreen TV, so widescreen art has to be authored
    wide and then pre-squashed. Squashing a *rendered* spiral with a resampling
    filter smears its crisp two-tone rings into gradients -- hundreds of colours
    that then cost three times the byte budget in PNG. Baking the compression
    into the geometry instead keeps the output two-tone and cheap.
    """
    w, h = size
    cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
    # supersampled pixel-centre grid
    off = (np.arange(ss) + 0.5) / ss - 0.5
    ys = (np.arange(h)[:, None] + off[None, :]).ravel() - cy
    xs = (np.arange(w)[:, None] + off[None, :]).ravel() - cx
    dy, dx = ys[:, None], xs[None, :] / xscale
    r = np.hypot(dx, dy)
    th = np.arctan2(dy, dx)
    s = (r - pitch * th / (2 * np.pi) + phase) % pitch
    lit = (s < pitch * DUTY).astype(np.float32)
    # box-average each ss x ss cell back down -> antialiased coverage in [0,1]
    cov = lit.reshape(h, ss, w, ss).mean(axis=(1, 3))
    if levels:
        cov = np.rint(cov * levels) / levels
    cov = cov[:, :, None]
    rgb = np.array(LIGHT, np.float32) * cov + np.array(DARK, np.float32) * (1 - cov)
    return Image.fromarray(np.rint(rgb).astype(np.uint8), "RGB")


def verify_against(path, tol=0.6):
    """Render at `path`'s size and report mean/max per-channel error.

    A centred crop of the generated spiral must reproduce the source art; this
    is what justifies substituting a regenerated square for the hand-made PNG.
    """
    src = Image.open(path).convert("RGB")
    gen = render(src.size)
    a = np.asarray(src, np.float32)
    b = np.asarray(gen, np.float32)
    err = np.abs(a - b)
    mean, mx = err.mean(), err.max()
    ok = mean <= tol
    print(f"  spiral vs {path}: mean err {mean:.3f}, max {mx:.0f} "
          f"({'match' if ok else 'MISMATCH'})")
    return ok, mean, mx


if __name__ == "__main__":
    import os
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    for p in (("banner", "bg.png"), ("icon", "icon_bg.png")):
        verify_against(os.path.join(root, *p))
