"""Shared configuration: paths, donor, measured art geometry, animation timing.

Everything tunable about the channel lives here so the builders stay readable.

Coordinate systems
------------------
The art is authored at 832x456 (banner) and 176x96 (icon) with the *centre*
aligned to the viewport centre -- see Icon_Sizing.md. brlyt panes use a
centre-origin system with +y pointing up, so converting an authored pixel
position to a pane translate is:

    pane_x = px - W/2        pane_y = H/2 - py

Only the middle 608x456 of the banner (and 128x96 of the icon) is visible on a
4:3 TV; the rest is widescreen bleed. `safe_box` returns that 4:3 rectangle and
verify.py asserts every visible sprite stays inside it.
"""

import os
import subprocess

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BUILD = os.path.join(ROOT, "build")
OUT = os.path.join(BUILD, "out")
EXTRACTED = os.path.join(BUILD, "extracted")
BENZIN = os.path.join(BUILD, "tools", "benzin")
DONOR = os.path.join(ROOT, "donor", "FCE Ultra GX - FCEU [Tantric].wad")

# Source art, one directory per thing it feeds. Defined here rather than in each
# builder so moving an asset is a one-line change instead of a grep.
ICON_DIR = os.path.join(ROOT, "icon")
BANNER_DIR = os.path.join(ROOT, "banner")
SPLASH_DIR = os.path.join(ROOT, "splash")
AUDIO_DIR = os.path.join(ROOT, "audio")
PREVIEW_DIR = os.path.join(ROOT, "preview")

# ----------------------------------------------------------------- the channel

TITLE = "Z-GX"
TITLE_ID = "ZGXA"                # 00010001 5A475841; not a system or known-homebrew ID
APP_DIR = "ZGX"                  # forwarder boots sd:/apps/ZGX/boot.dol
# Release filename convention across Jaxi's channels: "<title> - <id> [<user>].wad",
# matching "mGBA-GX - GBGX [cmyksoda].wad" and "LSD Dream Emulator - LSDE [cmyksoda].wad".
USERNAME = "cmyksoda"
WAD_NAME = f"{TITLE} - {TITLE_ID} [{USERNAME}].wad"

# ------------------------------------------------------------------- viewports

FPS = 60
BANNER_ART = (832, 456)          # authored size, incl. 112 px widescreen bleed each side
BANNER_43 = (608, 456)           # what a 4:3 TV actually shows
ICON_ART = (176, 96)             # incl. 24 px bleed each side
ICON_43 = (128, 96)

# The Wii Menu draws its own title bar and Start button over the bottom of the
# banner, so the usable area is not vertically centred and a geometrically
# centred spiral reads as sitting too low. This lifts the spiral's centre only.
#
# The sprites are NOT lifted here, because banner.png already carries the lift:
# Jaxi's revised composition raised the logo 36 px and the console 31.5 px, and
# PLACEMENT below is measured from it. Adding another 50 on top would push the
# logo off the top edge.
SPIRAL_LIFT_Y = 50.0

# Extra lift applied to the sprites on top of banner.png, if the composition ever
# needs nudging without re-exporting the art.
SPRITE_LIFT_Y = 0.0

# ------------------------------------------------- measured art placement
#
# Where each asset's **opaque bounding-box centre** sits, in pane coordinates.
#
# Anchoring on the bbox centre rather than a top-left pixel is deliberate: it
# survives an asset being re-exported at a different size or with different
# transparent padding, which is exactly what happened when saturnmk2.png went
# from 410x228 to 420x238. A top-left placement silently shifts the artwork in
# that situation; a bbox-centre placement keeps it where it was composed and just
# lets it change size.
#
# Both values were derived from Jaxi's banner.png, where a best-offset search
# located the original assets to within 0.09/255 (logo) and 0.86/255 (console) --
# so this is the authored composition, not a guess.
PLACEMENT = {
    "logo.png": (-85.5, 146.5),
    "saturnmk2.png": (99.0, -4.0),
}


def spinner_side(lift, safe=BANNER_43, margin=8):
    """Smallest multiple-of-8 square that covers the 16:9 frame while rotating.

    A pane rotates about its own centre, so the square's inscribed circle has to
    reach the frame's furthest corner *from that centre*. Lifting the spiral moves
    the centre away from the bottom corners, so the square has to grow -- deriving
    it here instead of hardcoding means SPIRAL_LIFT_Y cannot silently outgrow it
    and reintroduce black wedges. 8 because CI4 tiles are 8x8.
    """
    wide_w = safe[0] * 4.0 / 3.0                 # the Menu reveals 4/3 more width
    need = 2.0 * (( (wide_w / 2.0) ** 2 + (safe[1] / 2.0 + abs(lift)) ** 2 ) ** 0.5)
    return int(-(-(need + margin) // 8) * 8)


BANNER_SPIRAL = spinner_side(SPIRAL_LIFT_Y)          # 992 at a 50 px lift
ICON_SPIRAL = spinner_side(0.0, safe=ICON_43)        # 208; the icon is not lifted

# Texels stored per layout unit for the spinning background.
#
# A rotating square has to cover the frame's diagonal, so at 1:1 it stores 2.6x
# more texels than are ever visible at once (992^2 against 832x456) -- and that
# was 492 KB, 59% of the whole banner. Banner memory is shared across every
# installed channel, so it is worth buying back.
#
# The pitch is scaled with it, so the rings stay 10 layout units apart on screen;
# only the texel density drops and GX's bilinear filter smooths the difference.
# At 0.75 the result is indistinguishable from 1:1 at viewing scale (mean
# difference 5.5/255, ring contrast 99% retained) for 215 KB less. 0.5 saves 369 KB
# and is still faithful (contrast 97%) but visibly softer on the fine outer rings.
SPIRAL_TEXEL_SCALE = 0.75
BANNER_SPIRAL_TEX = int(round(BANNER_SPIRAL * SPIRAL_TEXEL_SCALE / 8)) * 8   # 744

# ------------------------------------------------------------- banner animation
#
# Timing follows the brief: console pops immediately, logo flies in at ~1 s.
# The squash/stretch numbers and the idle bob are lifted verbatim from Tantric's
# FCE Ultra GX / Snes9x GX banner (identical layout in both) -- his LogoPicture
# does X Translation 1024 -> -120 over 60 frames with X Scale 1/1/0.7/1 and
# Y Scale 1/1/1.2/1 at frames 0/59/66/69. Only the direction is mirrored, so the
# logo arrives from the left instead of the right.
BANNER_FRAMES = 1000             # donor's framesize for both Start and Loop; left alone

CONSOLE_POP = 30                 # frames for scale 0 -> 1 (0.5 s)
# The donor overshoots to 1.2 before settling. Jaxi's composition puts the
# console's right edge 1 px inside the 4:3 viewport, so *any* overshoot would
# clip it on a 4:3 TV -- hence a straight ease to 1.0. Raise this only if the
# console is moved left first.
CONSOLE_OVERSHOOT = 1.0

LOGO_WAIT = 60                   # hold off-screen for 1.0 s, so the console lands first
LOGO_FLY = 60                    # frames of travel (donor's own duration)
LOGO_OFFSCREEN_X = -1024.0       # start well left of the widescreen edge
SQUISH_LEAD = 1                  # squash begins 1 frame before landing (donor: 59 vs 60)
SQUISH_PEAK = 6                  # frames after landing to peak squash (donor: 66)
SQUISH_END = 9                   # fully recovered (donor: 69)
SQUASH_X = 0.7                   # donor values, unchanged
STRETCH_Y = 1.2
# The donor's idle float on the logo, 0 -> BOB_AMPLITUDE -> 0. Disabled: with the
# banner shifted up 50 px the logo's top edge is 5 px from the viewport edge, and
# a 15 px lift would clip it. It was inherited from the donor's logo animation
# rather than asked for, so it is the thing that gives way.
BOB_AMPLITUDE = 0
BOB_HALF = 125

# --------------------------------------------------------------- icon animation

# 2.0 s fade in, 2.0 s held fully visible, 2.0 s fade out = a 360-frame cycle.
# The framesize has to be a whole number of those or the fade is cut mid-cycle at
# the loop wrap and visibly pops, so 1080 = 3 cycles (18 s). The donor's own 1200
# would give 3.33 cycles.
ICON_FADE = 120
ICON_HOLD = 120
ICON_FRAMES = 1080

# ------------------------------------------------------------------- the spiral
#
# Negative is clockwise, because brlyt +y points up (confirmed by rendering the
# unmodified donor: its icon logo sits above its ground sprites).
#
# Speed needs care, and the first build got it wrong. An Archimedean spiral is
# effectively rotation-invariant in *appearance*: rotating it by theta produces an
# image identical to shifting its rings radially by (theta/360) x pitch -- 90 and
# 180 degree rotations here reproduce a phase shift bit for bit. So the thing the
# eye perceives is not degrees per second but **ring creep**, which is only one
# 10 px pitch per whole revolution. At the original one turn per cycle (21.6 deg/s)
# that is 0.6 px/s and reads as completely static, which is exactly how it looked.
#
# These give ~0.5 revolutions per second, so the rings drift ~5 px/s: clearly
# moving, still unhurried. Each must stay a whole number of turns, because a full
# 360 deg returns the square pane to the orientation it started in and anything
# else snaps at the loop wrap.
BANNER_TURNS = -8.0              # over 1000 frames -> 172.8 deg/s, 0.48 rev/s
ICON_TURNS = -9.0                # over 1080 frames -> 180.0 deg/s, 0.50 rev/s

# Clockwise rotation makes the rings appear to travel *inward* (increasing phase
# moves each band toward the centre) -- the classic hypnotic-spiral direction.

# ---------------------------------------------------------------- icon logo size
#
# Scales the icon logo texture down; the pane is resized to match so the Wii
# never resamples it. 0.8 = 20% smaller.
ICON_LOGO_SCALE = 0.8


def benzin(*args):
    """Run Benzin under wine. 'r' rips a binary to XML, 'm' makes it back."""
    r = subprocess.run(["wine", "BENZIN.EXE", *args], cwd=BENZIN,
                       capture_output=True, env={**os.environ, "WINEDEBUG": "-all"})
    out = (r.stdout + r.stderr).decode(errors="replace")
    if "Couldn't" in out or r.returncode != 0:
        raise RuntimeError(f"benzin {args}: {out}")
    return out


def to_pane(px, py, art=BANNER_ART):
    """Authored top-left-origin pixel -> centre-origin pane coords (+y up)."""
    w, h = art
    return px - w / 2.0, h / 2.0 - py


def safe_box(art=BANNER_ART, safe=BANNER_43):
    """The 4:3 rectangle, in pane coords, that a 4:3 TV actually shows."""
    return (-safe[0] / 2.0, -safe[1] / 2.0, safe[0] / 2.0, safe[1] / 2.0)


def ceil4(n):
    return (n + 3) // 4 * 4


def opaque_bbox(img):
    """(left, top, right, bottom) of everything not fully transparent."""
    bb = img.convert("RGBA").getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    return bb if bb else (0, 0, img.size[0], img.size[1])


def place(img, target, shift_y=0.0):
    """Pad an asset to 4-aligned texture dimensions and say where its pane goes.

    GX tiles are 4x4, so a texture's width and height must both be multiples of 4.
    Returns (canvas_size, paste_offset, pane_translate): paste the asset into a
    transparent canvas of `canvas_size` at `paste_offset`, size the pane to
    `canvas_size`, and translate it to `pane_translate`.

    `target` is where the asset's *opaque bounding-box centre* should land, in
    pane coordinates, and `shift_y` lifts it. Working from the bbox centre means
    re-exporting an asset at a different size or with different transparent
    padding keeps it composed where it was instead of sliding it sideways.
    """
    w, h = img.size
    cw, ch = ceil4(w), ceil4(h)
    ox, oy = (cw - w) // 2, (ch - h) // 2
    l, t, r, b = opaque_bbox(img)
    # bbox centre within the padded canvas, and the canvas's own centre
    bcx, bcy = ox + (l + r) / 2.0, oy + (t + b) / 2.0
    # pane translate = where the canvas centre goes; +y is up, so dy flips
    tx = target[0] - (bcx - cw / 2.0)
    ty = target[1] + shift_y + (bcy - ch / 2.0)
    return (cw, ch), (ox, oy), (tx, ty)
