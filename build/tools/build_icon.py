"""Build icon.bin: the spiral spins clockwise, the Z-GX logo pulses.

    BackgroundPicture  <- 208x208 spiral, RLPA Z Rotate 0 -> -9 turns, linear
    Logo00Picture      <- icon_logo.png at 80%, RLVC pane alpha 0 -> 255 -> 0

Both run inside a 1080-frame (18 s) loop: three 2 s-in / 2 s-hold / 2 s-out fade
cycles, and nine revolutions of the spiral at 180 deg/s. That both divide evenly
matters -- a fade caught mid-cycle at the wrap would pop, and a rotation that is
not a whole multiple of 360 deg would snap the spiral back.

Why 208x208 for a 176x96 viewport
---------------------------------
A pane rotates about its centre, so the corners of a viewport-sized pane would
sweep inside the frame and show black wedges. The pane has to be a square whose
inscribed circle covers the frame: hypot(176, 96) = 200.5, rounded up to 208
(`zgx.spinner_side` derives it). See spiral.py for why regenerating the art
rather than resizing icon_bg.png is the faithful option.

The animation is written from scratch instead of patched
-------------------------------------------------------
The donor's icon brlan drives `Logo00Material` with an RLTP texture-swap track
that cycles between Logo00.tpl and Logo01.tpl. Logo01 becomes a 4x4 stub here,
so keeping that track would flicker the logo out of existence several times a
second. Emitting a fresh brlan drops every RLTP track at once, which is both
safer and clearer than surgically removing them.

The 102,400-byte cap
--------------------
`icon.bin` must decompress to at most 0x19000. That is a hard check inside the
System Menu, not a budget -- over it, the buffer is never allocated and the
Menu's LZ77 decompressor writes into address 0, bricking it right after the
Health & Safety screen. This icon lands near 56% of the cap.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from PIL import Image

import brlan as A
import brlyt as L
import spiral as S
import tex
from wiilib import U8, pack_lz77_imd5, unpack_lz77_imd5
from zgx import (BENZIN, BUILD, EXTRACTED, ICON_ART, ICON_DIR, ICON_FADE,
                 ICON_FRAMES, ICON_HOLD, ICON_LOGO_SCALE, ICON_SPIRAL,
                 ICON_TURNS, OUT, benzin, opaque_bbox, place)

ICON_CAP = 0x19000                      # 102,400 -- enforced by the System Menu

SPIRAL_PANE = "BackgroundPicture"
LOGO_PANE, LOGO_PICTURE = "Logo00Pane", "Logo00Picture"
SPIRAL_TEX, LOGO_TEX = "Background.tpl", "Logo00.tpl"
SPIRAL_MAT, LOGO_MAT = "BackgroundMaterial", "Logo00Material"

# Sprite frames for the donor's Mario/Goomba/second-logo cels. Nothing in the
# rewritten layout or animation references them, and the texture list never did
# (it names only four), so they can be removed outright rather than stubbed.
DROP = ["Logo01.tpl", "Mario01.tpl", "Mario02.tpl", "Goomba01.tpl", "Goomba02.tpl"]
# These two *are* in the texture list, so they stay as 4x4 stubs.
STUBS = ["Mario00.tpl", "Goomba00.tpl"]


def fade_keys():
    """Pane alpha: fade up, hold at full, fade down, repeated to the framesize.

    Smoothstep (zero tangents) rather than linear, so the logo eases in and out
    instead of ramping mechanically -- the same curve Tantric's fades use. The
    hold is why ICON_FRAMES is 1080 rather than the donor's 1200: the cycle is
    now 360 frames and the framesize has to be a whole number of them, or the
    fade gets cut mid-cycle at the loop wrap and visibly pops.
    """
    cycle = 2 * ICON_FADE + ICON_HOLD
    assert ICON_FRAMES % cycle == 0, (
        f"ICON_FRAMES {ICON_FRAMES} is not a whole number of {cycle}-frame fade "
        f"cycles; the loop would pop")
    pts, f = [], 0
    while f < ICON_FRAMES:
        pts += [(f, 0), (f + ICON_FADE, 255), (f + ICON_FADE + ICON_HOLD, 255)]
        f += cycle
    pts.append((ICON_FRAMES, 0))
    return A.smooth(pts)


def spin_keys(frames):
    """Whole turns, linear so the speed never wavers. See zgx.py on the rate --
    this spiral reads as ring creep, not as degrees, so one turn was invisible."""
    return A.linear([(0, 0.0), (frames, 360.0 * ICON_TURNS)])


def scaled_logo():
    """The icon logo at ICON_LOGO_SCALE, plus its texture size and pane translate.

    Scaled here rather than by a pane scale, so the Wii never resamples it and the
    texture stays 1:1 with its pane. Cropping to the opaque bbox first means the
    scale applies to the artwork rather than to icon_logo.png's transparent
    margins, and `place` re-centres whatever comes out.
    """
    src = Image.open(os.path.join(ICON_DIR, "icon_logo.png")).convert("RGBA")
    assert src.size == ICON_ART, f"icon_logo.png is {src.size}, need {ICON_ART}"
    art = src.crop(opaque_bbox(src))
    small = art.resize((max(1, round(art.width * ICON_LOGO_SCALE)),
                        max(1, round(art.height * ICON_LOGO_SCALE))), Image.LANCZOS)
    size, off, at = place(small, (0.0, 0.0))
    return tex.pad_to(small, size, off), size, at, art.size, small.size


def main():
    arc = U8.load(unpack_lz77_imd5(open(f"{EXTRACTED}/icon.bin", "rb").read()))
    logo, logo_size, logo_at, art_size, small_size = scaled_logo()

    # ---------------------------------------------------------------- layout
    open(f"{BENZIN}/i_src.brlyt", "wb").write(arc.get("/arc/blyt/icon.brlyt"))
    benzin("r", "i_src.brlyt", "i_src.xmlyt")
    x = open(f"{BENZIN}/i_src.xmlyt").read()
    x = L.edit_panes(x, {
        SPIRAL_PANE: {"translate": (0.0, 0.0), "size": (ICON_SPIRAL, ICON_SPIRAL)},
        # Logo00Pane ships alpha=b4 (180); edit_panes forces ff so the fade is full range
        LOGO_PANE: {"translate": (0.0, 0.0)},
        LOGO_PICTURE: {"translate": logo_at, "size": logo_size},
    })
    x = L.identity_materials(x, {SPIRAL_MAT, LOGO_MAT})
    open(f"{BENZIN}/i_new.xmlyt", "w").write(x)
    benzin("m", "i_new.xmlyt", "i_new.brlyt")
    arc.replace("/arc/blyt/icon.brlyt", open(f"{BENZIN}/i_new.brlyt", "rb").read())

    # ------------------------------------------------------------- animation
    doc = A.document(ICON_FRAMES, [
        A.pane(SPIRAL_PANE, [("RLPA", [(A.Z_ROT, spin_keys(ICON_FRAMES))])]),
        A.pane(LOGO_PICTURE, [("RLVC", [(A.PANE_ALPHA, fade_keys())])]),
    ])
    open(f"{BENZIN}/i_new.xmlan", "w").write(doc)
    benzin("m", "i_new.xmlan", "i_new.brlan")
    arc.replace("/arc/anim/icon.brlan", open(f"{BENZIN}/i_new.brlan", "rb").read())

    # -------------------------------------------------------------- textures
    sp = S.render((ICON_SPIRAL, ICON_SPIRAL), levels=15)
    data, note = tex.spiral_tpl(sp)
    arc.replace(f"/arc/timg/{SPIRAL_TEX}", data)
    print(f"  spiral   {ICON_SPIRAL}x{ICON_SPIRAL} {note}")

    arc.replace(f"/arc/timg/{LOGO_TEX}", tex.sprite_tpl(logo))
    print(f"  logo     {art_size[0]}x{art_size[1]} art x{ICON_LOGO_SCALE:g} -> "
          f"{small_size[0]}x{small_size[1]} in a {logo_size[0]}x{logo_size[1]} "
          f"RGB5A3 texture at pane {logo_at}")

    for name in STUBS:
        arc.replace(f"/arc/timg/{name}", tex.stub_tpl())
    for name in DROP:
        i = arc.find(f"/arc/timg/{name}")
        arc.nodes.pop(i)
        for nd in arc.nodes:            # keep directory node ranges correct
            if nd.is_dir and nd.last > i:
                nd.last -= 1

    # ----------------------------------------------------------------- pack
    raw = arc.to_bytes()
    problems = arc.check_tree()
    assert not problems, problems
    assert len(raw) <= ICON_CAP, (
        f"icon.bin is {len(raw):,} bytes, over the System Menu's {ICON_CAP:,}-byte "
        "cap -- this bricks the Menu after the Health & Safety screen")
    os.makedirs(OUT, exist_ok=True)
    open(f"{OUT}/icon_u8.bin", "wb").write(raw)
    packed = pack_lz77_imd5(raw)
    open(f"{OUT}/icon.bin", "wb").write(packed)

    deg = 360.0 * abs(ICON_TURNS) / (ICON_FRAMES / 60.0)
    print(f"  icon.bin: {len(raw):,} uncompressed -> {len(packed):,} stored "
          f"({len(raw)/ICON_CAP:.0%} of the {ICON_CAP:,}-byte cap)")
    rev = abs(ICON_TURNS) * 60 / ICON_FRAMES
    print(f"  spin: {ICON_TURNS:+g} turns over {ICON_FRAMES} frames "
          f"({deg:.1f} deg/s, {rev:.2f} rev/s, rings creep {rev*10:.1f} px/s "
          f"{'clockwise/inward' if ICON_TURNS < 0 else 'anticlockwise/outward'})")
    print(f"  fade: {ICON_FADE/60:.1f}s in / {ICON_HOLD/60:.1f}s hold / "
          f"{ICON_FADE/60:.1f}s out, "
          f"{ICON_FRAMES//(2*ICON_FADE+ICON_HOLD)} cycles per {ICON_FRAMES/60:.0f}s loop")


if __name__ == "__main__":
    main()
