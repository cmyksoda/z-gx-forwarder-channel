"""Build banner.bin: spiral spins, Saturn pops open, Z-GX logo flies in squishy.

    BackgroundPicture <- 960x960 spiral      Z Rotate 0 -> -360 deg, linear
    ControllerPicture <- saturnmk2.png       X/Y Scale 0 -> 1 over 30 frames
    LogoPicture       <- logo.png            X Translation in from the left at
                                             frame 60, landing at 120, then a
                                             squash/stretch on impact, then an
                                             idle bob for as long as it is shown

Everything else in Tantric's layout is set invisible and its texture shrunk to a
4x4 stub that keeps its name, so every texture-list entry and every RLTP
reference in either brlan still resolves.

The squish
----------
Not invented. Tantric's FCE Ultra GX and Snes9x GX banners share one layout, and
his `LogoPicture` already flies in and squashes on landing:

    X Translation  0:1024   60:-120
    X Scale        0:1  59:1  66:0.7  69:1
    Y Scale        0:1  59:1  66:1.2  69:1
    Y Translation  0:0  125:15  250:0  375:15 ...        (idle float)

Those scale numbers and that 1-frame-early / 6-frame-peak / 9-frame-recovery
shape are reproduced verbatim. Only two things change: the travel is mirrored so
the logo arrives from the left, and the whole fly-in is delayed by 60 frames so
the console has finished opening first.

Because the squash starts one frame *before* the logo stops, and the travel eases
out, the compression reads as the logo planting itself rather than as a separate
wobble. The recovery is deliberately asymmetric -- 6 frames in, 3 out -- which is
what makes it snap.

Why the console does not overshoot
----------------------------------
The donor's controller pops to 1.2x before settling. It cannot here: the console
sits with its right edge 1 px inside the 4:3 viewport, so any scale above 1.0
would clip it on a 4:3 TV for the few frames of the overshoot. `CONSOLE_OVERSHOOT`
in zgx.py is the knob; it needs the console moved left before it can be raised.

Resting values match the layout
-------------------------------
Every track ends on the value the brlyt already holds -- logo X translation 0,
console scale 1.0 -- so the Start -> Loop hand-off cannot jump, and neither can a
Menu that rebinds panes from layout defaults. (The donor is not like this: its
logo ends at -120 while its brlyt says 0, and it relies on pane state persisting.)
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
from zgx import (BANNER_ART, BANNER_DIR, BANNER_FRAMES, BANNER_SPIRAL,
                 BANNER_SPIRAL_TEX, BANNER_TURNS, BENZIN,
                 BOB_AMPLITUDE, BOB_HALF, CONSOLE_OVERSHOOT, CONSOLE_POP, EXTRACTED,
                 LOGO_FLY, LOGO_OFFSCREEN_X, LOGO_WAIT, OUT, PLACEMENT,
                 SPIRAL_LIFT_Y, SPRITE_LIFT_Y, SQUASH_X, SQUISH_END, SQUISH_LEAD,
                 SQUISH_PEAK, STRETCH_Y, benzin, place)

BANNER_BUDGET = 1388896          # FCEUGX's own banner; two ~2.5 MB banners freeze the Menu

SPIRAL_PANE = "BackgroundPicture"
CONSOLE_PANE, CONSOLE_PICTURE = "ControllerPane", "ControllerPicture"
LOGO_PANE, LOGO_PICTURE = "LogoPane", "LogoPicture"
SPIRAL_TEX, CONSOLE_TEX, LOGO_TEX = "Background.tpl", "Controller.tpl", "Logo.tpl"
SPIRAL_MAT, CONSOLE_MAT, LOGO_MAT = ("BackgroundMaterial", "ControllerMaterial",
                                     "LogoMaterial")

# Donor tracks we replace. BackgroundMaterial carries the RLTS texture scroll
# that used to slide his tiled background sideways; the spiral is a rotating
# pane instead, so the material animation goes entirely and the material keeps
# the identity matrix the layout now gives it.
REPLACED = [SPIRAL_MAT, CONSOLE_PICTURE, LOGO_PICTURE]

LAND = LOGO_WAIT + LOGO_FLY      # frame the logo comes to rest


def spin():
    """Whole turns, linear -- constant speed and a seamless wrap.

    See zgx.py for why the rate is what it is: this spiral looks identical under
    rotation and under a radial phase shift, so what the eye reads is ring creep,
    one 10 px pitch per revolution. One turn per cycle was invisible.
    """
    return A.linear([(0, 0.0), (BANNER_FRAMES, 360.0 * BANNER_TURNS)])


def bob():
    """The donor's idle float: 0 -> BOB_AMPLITUDE -> 0 every BOB_HALF frames.

    Starts and ends at 0, so it wraps without a step, and 0 is the logo's
    authored position -- the float only ever lifts it, so the banner at rest is
    exactly Jaxi's banner.png. Set BOB_AMPLITUDE = 0 in zgx.py for a dead-still
    logo; this track is inherited from the donor's logo animation rather than
    asked for, and it is the one piece of motion here that is not in the brief.
    """
    pts, f, up = [], 0, False
    while f < BANNER_FRAMES:
        pts.append((f, BOB_AMPLITUDE if up else 0))
        up = not up
        f += BOB_HALF
    pts.append((BANNER_FRAMES, 0))
    return A.smooth(pts)


def console_scale():
    pts = [(0, 0.0), (CONSOLE_POP, CONSOLE_OVERSHOOT)]
    if CONSOLE_OVERSHOOT != 1.0:                  # settle back after the overshoot
        pts.append((CONSOLE_POP + 5, 1.0))
    return A.smooth(pts)


def fly_in():
    return A.smooth([(0, LOGO_OFFSCREEN_X), (LOGO_WAIT, LOGO_OFFSCREEN_X), (LAND, 0.0)])


def squish(peak):
    return A.smooth([(0, 1.0), (LAND - SQUISH_LEAD, 1.0),
                     (LAND + SQUISH_PEAK, peak), (LAND + SQUISH_END, 1.0)])


def main():
    arc = U8.load(unpack_lz77_imd5(open(f"{EXTRACTED}/banner.bin", "rb").read()))

    logo_src = Image.open(os.path.join(BANNER_DIR, "logo.png")).convert("RGBA")
    console_src = Image.open(os.path.join(BANNER_DIR, "saturnmk2.png")).convert("RGBA")
    logo_size, logo_off, logo_at = place(logo_src, PLACEMENT["logo.png"], SPRITE_LIFT_Y)
    con_size, con_off, con_at = place(console_src, PLACEMENT["saturnmk2.png"],
                                      SPRITE_LIFT_Y)

    # ---------------------------------------------------------------- layout
    open(f"{BENZIN}/b_src.brlyt", "wb").write(arc.get("/arc/blyt/banner.brlyt"))
    benzin("r", "b_src.brlyt", "b_src.xmlyt")
    x = open(f"{BENZIN}/b_src.xmlyt").read()
    x = L.edit_panes(x, {
        # lifted so it reads as centred in the area the Menu's title bar leaves
        SPIRAL_PANE: {"translate": (0.0, SPIRAL_LIFT_Y),
                      "size": (BANNER_SPIRAL, BANNER_SPIRAL)},
        CONSOLE_PANE: {"translate": con_at},
        CONSOLE_PICTURE: {"translate": (0.0, 0.0), "size": con_size},
        # anchored exactly where banner.png puts it
        LOGO_PANE: {"translate": logo_at},
        LOGO_PICTURE: {"translate": (0.0, 0.0), "size": logo_size},
    })
    x = L.identity_materials(x, {SPIRAL_MAT, CONSOLE_MAT, LOGO_MAT})
    open(f"{BENZIN}/b_new.xmlyt", "w").write(x)
    benzin("m", "b_new.xmlyt", "b_new.brlyt")
    arc.replace("/arc/blyt/banner.brlyt", open(f"{BENZIN}/b_new.brlyt", "rb").read())

    # ------------------------------------------------------------ animations
    for name in ("banner_Start", "banner_Loop"):
        open(f"{BENZIN}/a_{name}.brlan", "wb").write(arc.get(f"/arc/anim/{name}.brlan"))
        benzin("r", f"a_{name}.brlan", f"a_{name}.xmlan")
        a = A.drop_panes(open(f"{BENZIN}/a_{name}.xmlan").read(), REPLACED)
        blocks = [A.pane(SPIRAL_PANE, [("RLPA", [(A.Z_ROT, spin())])])]
        if name == "banner_Start":
            blocks += [
                A.pane(CONSOLE_PICTURE, [("RLPA", [(A.X_SCALE, console_scale()),
                                                   (A.Y_SCALE, console_scale())])]),
                A.pane(LOGO_PICTURE, [("RLPA", [(A.X_TRANS, fly_in()),
                                                (A.X_SCALE, squish(SQUASH_X)),
                                                (A.Y_SCALE, squish(STRETCH_Y)),
                                                (A.Y_TRANS, bob())])]),
            ]
        else:
            # the console holds the layout's scale 1.0; the logo only floats.
            # Dropping the donor's +/-10 deg console sway too -- it was not asked
            # for, and rotating a pane this close to the 4:3 edge clips it.
            blocks.append(A.pane(LOGO_PICTURE, [("RLPA", [(A.Y_TRANS, bob())])]))
        a = A.add_panes(a, blocks)
        open(f"{BENZIN}/a_{name}_new.xmlan", "w").write(a)
        benzin("m", f"a_{name}_new.xmlan", f"a_{name}_new.brlan")
        arc.replace(f"/arc/anim/{name}.brlan",
                    open(f"{BENZIN}/a_{name}_new.brlan", "rb").read())

    # -------------------------------------------------------------- textures
    # Stored below 1:1 and stretched over the pane by GX. The pitch scales with
    # it so the rings still land 10 layout units apart on screen; see
    # SPIRAL_TEXEL_SCALE in zgx.py for why, and what it costs.
    sp = S.render((BANNER_SPIRAL_TEX, BANNER_SPIRAL_TEX),
                  pitch=S.PITCH * BANNER_SPIRAL_TEX / BANNER_SPIRAL, levels=15)
    data, note = tex.spiral_tpl(sp)
    print(f"  spiral   {BANNER_SPIRAL_TEX}x{BANNER_SPIRAL_TEX} texels over a "
          f"{BANNER_SPIRAL}x{BANNER_SPIRAL} pane  {note}")

    con_tpl, con_err = tex.ci8_sprite_tpl(tex.pad_to(console_src, con_size, con_off))
    logo_tpl, logo_err = tex.ci8_sprite_tpl(tex.pad_to(logo_src, logo_size, logo_off))
    real = {SPIRAL_TEX: data, CONSOLE_TEX: con_tpl, LOGO_TEX: logo_tpl}
    print(f"  console  {con_size[0]}x{con_size[1]} CI8 (err {con_err:.2f}/255) at pane {con_at}")
    print(f"  logo     {logo_size[0]}x{logo_size[1]} CI8 (err {logo_err:.2f}/255) at pane {logo_at}")

    stubbed = 0
    for i, p in list(arc.paths()):
        if not p.endswith(".tpl"):
            continue
        base = os.path.basename(p)
        if base in real:
            arc.replace(p, real.pop(base))
        else:
            arc.replace(p, tex.stub_tpl())
            stubbed += 1
    assert not real, f"textures not found in donor archive: {sorted(real)}"

    # ----------------------------------------------------------------- pack
    problems = arc.check_tree()
    assert not problems, problems
    raw = arc.to_bytes()
    packed = pack_lz77_imd5(raw)
    os.makedirs(OUT, exist_ok=True)
    open(f"{OUT}/banner_u8.bin", "wb").write(raw)
    open(f"{OUT}/banner.bin", "wb").write(packed)

    deg = 360.0 * abs(BANNER_TURNS) / (BANNER_FRAMES / 60.0)
    print(f"  banner.bin: {len(raw):,} uncompressed -> {len(packed):,} stored")
    print(f"  budget: {len(raw)/BANNER_BUDGET:.1%} of FCEUGX's {BANNER_BUDGET:,}-byte banner"
          f"  ({stubbed} textures stubbed to 4x4, names kept)")
    print(f"  spin : {deg:.1f} deg/s clockwise ({abs(BANNER_TURNS)*60/BANNER_FRAMES:.2f} rev/s, "
          f"rings creep {abs(BANNER_TURNS)*60/BANNER_FRAMES*10:.1f} px/s), "
          f"{abs(BANNER_TURNS):g} turns per {BANNER_FRAMES}-frame loop")
    print(f"  spiral lifted {SPIRAL_LIFT_Y:+g} to clear the Menu's title bar")
    print(f"  pop  : console scale 0 -> {CONSOLE_OVERSHOOT:g} over {CONSOLE_POP} frames "
          f"({CONSOLE_POP/60:.2f}s)")
    print(f"  fly  : logo waits {LOGO_WAIT/60:.1f}s, travels {LOGO_FLY} frames from "
          f"x={LOGO_OFFSCREEN_X:g}, lands frame {LAND}")
    print(f"  squish: X {SQUASH_X:g} / Y {STRETCH_Y:g} at frames "
          f"{LAND-SQUISH_LEAD}/{LAND+SQUISH_PEAK}/{LAND+SQUISH_END}")
    assert len(raw) <= BANNER_BUDGET, (
        f"banner is {len(raw):,} bytes, over FCEUGX's {BANNER_BUDGET:,} -- "
        "too much banner memory slows and then freezes the Wii Menu")


if __name__ == "__main__":
    main()
