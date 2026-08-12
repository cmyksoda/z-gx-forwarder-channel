"""Texture packing choices for this channel's art.

Format picking is not cosmetic here -- the icon has a hard 102,400-byte cap and
the banner a soft memory budget, and a rotating background is a big texture.

* **spiral -> CI4.** The spiral is two colours plus antialiasing, and
  `spiral.render(levels=15)` caps it at exactly 16 distinct colours, so a
  16-entry palette holds every one of them with **no colours merged** at 4 bits
  per pixel. 960x960 costs 460,800 bytes instead of 1,843,200 as RGBA8, which is
  what makes a full-coverage spinning background affordable. If the colour count
  ever exceeds 16 this falls back to CI8 rather than silently degrading.

  It is not bit-exact, and the check below does not claim it is: TPL palette
  entries are themselves stored as RGB5A3, so each entry lands within 5-bit
  precision of the original (max error 6/255 measured here, against 7/255 for
  RGB565 -- the format the previous project's background shipped in). What CI4
  *does* guarantee exactly is the index structure: no two distinct source
  colours collapse into one, so no banding is introduced on top of that.

* **sprites -> RGB5A3.** The console photo and the logo need alpha, and RGB5A3
  is what Tantric's own `Logo.tpl` and `Controller.tpl` use, so the System Menu
  demonstrably renders it. Its alpha is 3-bit, which is coarse in principle but
  is exactly what ships in every stock channel banner.

* **unused donor textures -> 4x4 stubs that keep their names.** Every entry in
  the layout's texture list and every RLTP reference in a brlan must still
  resolve, so the files stay; only their contents shrink. A flat 4x4 stretched
  over a pane is also how the donor's own solid-colour fills work, so this is
  not a hack.
"""

import numpy as np
from PIL import Image

import tpl as T

STUB = (4, 4)


RGB5A3_MAX_ERR = 8              # 5 bits per channel: worst case 255/31/2 rounded up


def spiral_tpl(img):
    """CI4 if the palette fits (it is designed to), else CI8. Returns (tpl, note).

    Verifies the two things that are actually guaranteed: every distinct source
    colour gets its own palette entry (nothing merges), and the decoded texture
    equals the source mapped through the RGB5A3-quantised palette *exactly* --
    i.e. the tiling and index packing are correct. The residual against the
    original is then purely the palette's 5-bit precision, and is reported.
    """
    for maxc, fmt, name in ((16, T.CI4, "CI4"), (256, T.CI8, "CI8")):
        q = T.quantize(img, maxc)
        if q is None:
            continue
        idx, pal = q
        data = T.build([(idx, fmt, pal, img.size)])
        info = T.parse(data)[0]
        back = np.asarray(T.decode(data[info["data_off"]:], info["w"], info["h"],
                                   fmt, info["pal"]).convert("RGB"), np.int16)
        # what the decode *should* be: source indices through the stored palette
        expect = np.asarray(info["pal"], np.int16)[:, :3][np.asarray(idx)]
        assert np.array_equal(back, expect), f"{name} tiling/index round-trip is wrong"
        err = int(np.abs(back - np.asarray(img.convert("RGB"), np.int16)).max())
        assert err <= RGB5A3_MAX_ERR, f"{name} palette error {err} exceeds RGB5A3's bound"
        return data, (f"{name} ({len(pal)}-entry palette, no colours merged, "
                      f"max palette error {err}/255)")
    raise RuntimeError("spiral needs more than 256 colours -- check levels=")


def sprite_tpl(img):
    assert img.size[0] % 4 == 0 and img.size[1] % 4 == 0, \
        f"{img.size} is not 4-aligned; GX tiles are 4x4"
    return T.build([(img, T.RGB5A3, None, img.size)])


CI8_MAX_MEAN_ERR = 6.0          # per channel, alpha-weighted


def ci8_sprite_tpl(img, colors=256):
    """Halve a sprite's cost by palettising it: 1 byte/px + 512 vs 2 bytes/px.

    Banner memory is shared across *every installed channel*, so a sprite that
    survives palettisation should be palettised. Measured on this art the cost is
    negligible -- mean error 2.5/255 for the console photo and 1.7/255 for the
    logo -- because both are a narrow palette to begin with (a grey console, and
    black text with a white outline over one red sphere).

    Alpha comes along: TPL palette entries are RGB5A3, so partially transparent
    antialiased edges survive. Pillow's FASTOCTREE is used because it is the one
    Pillow quantiser that considers the alpha channel.
    """
    assert img.size[0] % 4 == 0 and img.size[1] % 4 == 0, \
        f"{img.size} is not 4-aligned; GX tiles are 4x4"
    im = img.convert("RGBA")
    q = im.quantize(colors=colors, method=Image.Quantize.FASTOCTREE)
    raw = q.getpalette("RGBA")
    pal = [tuple(raw[i * 4:i * 4 + 4]) for i in range(colors)]
    idx = np.asarray(q, dtype=np.uint8)

    # error on premultiplied colour, so transparent padding cannot flatter it
    a = np.asarray(im, np.int16)
    p = np.asarray(pal, np.int16)[idx]
    err = np.abs(a[:, :, :3] * (a[:, :, 3:4] / 255.0)
                 - p[:, :, :3] * (p[:, :, 3:4] / 255.0))
    mean = float(err.mean())
    assert mean <= CI8_MAX_MEAN_ERR, (
        f"CI8 mean error {mean:.2f} exceeds {CI8_MAX_MEAN_ERR}; this sprite needs "
        f"RGB5A3")
    return T.build([(idx.tolist(), T.CI8, pal, im.size)]), mean


def stub_tpl():
    return T.build([(Image.new("RGBA", STUB, (0, 0, 0, 0)), T.RGB5A3, None, STUB)])


def pad_to(img, canvas, offset):
    """Paste an RGBA asset into a transparent canvas at `offset`."""
    out = Image.new("RGBA", canvas, (0, 0, 0, 0))
    out.paste(img.convert("RGBA"), offset)
    return out
