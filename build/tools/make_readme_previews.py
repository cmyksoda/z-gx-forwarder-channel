"""Render the four images README.md embeds, into `preview/` in the project root.

Separate from preview.py, which writes developer artefacts into build/out --
contact sheets with the safe area outlined, and long GIFs of the whole animation.
Those are diagnostic and build/out is gitignored. These four are committed, so
they have to stay small and be regenerable, or the README quietly rots.

Why these particular four. A 4:3 set shows the middle 608x456 of the banner and
the middle 128x96 of the icon; a 16:9 set shows the full authored extent, which is
4/3 *wider* and exactly as tall (see Icon_Sizing.md). Both matter, because the
composition has to survive either, so each asset is emitted at both extents.

Banners are stills and icons are GIFs, which is not laziness: the icon's whole
point is the fade, while the banner's animation is a one-off intro that a still
represents fine. A 100-frame banner GIF also came out at 8.8 MB -- a rotating
spiral changes every pixel every frame, so inter-frame compression buys nothing.
64-colour quantisation keeps the icon GIFs under 650 KB.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from PIL import Image

from preview import load, render_frame
from zgx import BANNER_43, BANNER_ART, ICON_43, ICON_ART, PREVIEW_DIR

PRE = PREVIEW_DIR

# The banner still: the console has popped (30) and the logo has landed (120) with
# its squash recovered (129), so this is the composition at rest.
BANNER_STILL = 200
# One 360-frame fade cycle of the icon's three, sampled every 6 ticks.
ICON_STEP, ICON_SPAN = 6, 360
GIF_COLORS = 64


def crop_43(img, art, safe):
    """The 4:3 rectangle a non-widescreen set actually shows."""
    return img.crop(((art[0] - safe[0]) // 2, 0, (art[0] + safe[0]) // 2, art[1]))


def save_gif(frames, path, step):
    q = [f.quantize(colors=GIF_COLORS, method=Image.Quantize.MEDIANCUT)
         for f in frames]
    q[0].save(path, save_all=True, append_images=q[1:],
              duration=int(1000 * step / 60), loop=0, optimize=True)


def main():
    os.makedirs(PRE, exist_ok=True)

    panes, tex, anims = load("banner")
    full = render_frame(panes, tex, anims["banner_Start"], BANNER_STILL,
                        BANNER_ART).convert("RGB")
    full.save(f"{PRE}/banner_16_9.png")
    crop_43(full, BANNER_ART, BANNER_43).save(f"{PRE}/banner_4_3.png")

    panes, tex, anims = load("icon")
    fr = [render_frame(panes, tex, anims["icon"], f, ICON_ART).convert("RGB")
          for f in range(0, ICON_SPAN, ICON_STEP)]
    save_gif(fr, f"{PRE}/icon_16_9.gif", ICON_STEP)
    save_gif([crop_43(f, ICON_ART, ICON_43) for f in fr],
             f"{PRE}/icon_4_3.gif", ICON_STEP)

    total = 0
    for f in sorted(os.listdir(PRE)):
        p = os.path.join(PRE, f)
        im = Image.open(p)
        total += os.path.getsize(p)
        print(f"  {f:<20} {im.size[0]:>3}x{im.size[1]:<3} "
              f"{getattr(im, 'n_frames', 1):>3} frame(s)  "
              f"{os.path.getsize(p)/1024:>6,.0f} KB")
    print(f"  {'preview/ total':<20} {'':>7} {'':>3}          {total/1024:>6,.0f} KB")


if __name__ == "__main__":
    main()
