"""Patch Tantric's FCE Ultra GX forwarder (content 2) to boot sd:/apps/ZGX.

Three in-place changes; the DOL keeps its original 934,656 bytes.

1. 4:3 splash PNG  at 0x081700 (165,683 bytes of room)
2. 16:9 splash PNG at 0x0A9E40 (157,270 bytes of room)
3. The app path format string, patched **where it already lives**.

No autoboot patch
-----------------
The previous project also rewrote the forwarder's command-line block, because
WiiStation only boots a game directly when handed argc >= 3. Z-GX is an ordinary
homebrew app: it wants no arguments, so Tantric's own one-argument code path is
exactly right and is left completely alone. `verify.py` asserts that region is
still byte-identical to the donor -- doing nothing is a claim worth checking.

The path string fits in place
-----------------------------
`%s:/apps/fceugx/boot.dol` sits in a 28-byte hole (the string, its NUL, and
three spare NULs before the next literal, "rb"). The previous project needed 18
characters for `LSD_Dream_Emulator` and so had to relocate the string into dead
space and repoint its lis/addi pair. `ZGX` is three characters, so
`%s:/apps/ZGX/boot.dol` is 22 bytes with its NUL and simply overwrites the old
one -- no relocation, no instruction patching, nothing to get wrong. The offset
is found by searching for the original string rather than hardcoded.

Splash byte budgets
-------------------
The replacement PNG must be no longer than the original and must stay
**colortype 2**: PNGU, Tantric's decoder, rejects palette PNGs outright, so the
obvious trick of palettising to shrink them is unavailable.

Stored losslessly, splash.png costs 226,383 bytes against a 165,683 budget --
the spiral's ~57 ring pairs are a lot of edges. The fix is to cut the number of
distinct *colours* while still writing RGB: the art is two spiral tones plus
black text and a white outline, so a small palette costs almost nothing visually
and compresses enormously (24 colours: 151,993 bytes). `encode_png` walks a
ladder from best to worst and stops at the first setting that fits, so quality is
only ever reduced as far as the budget forces. Nothing is blurred -- this is
synthetic art with crisp edges, and the previous project's kuwahara/despeckle
ladder (built for a noisy photographic scan) would only smear it.

The 16:9 splash
---------------
The Wii always renders 640x480 and lets the TV stretch it, so widescreen art is
authored at 854x480 and pre-squashed to 640x480; the stretch cancels the squash.
Squashing splash.png with a resampling filter turns its crisp two-tone rings
into gradients -- 2,000+ colours, three times the budget, and visible mush. So
the spiral is instead re-rendered *already elliptical* (spiral.render(xscale=))
which stays two-tone, and only the "LOADING..." text is resampled onto it.

The text is separated from its background using the fitted spiral model: against
a re-render, text pixels differ by >=200 (L1 over RGB) and sit in one block at
the top left, while the scattered 60..200 residue is just antialiasing where the
model and the source disagree by a hair. Taking the >=200 core, dilating it, and
soft-masking only inside that region yields the text with clean edges and no
spiral contamination. The previous project instead squashed to 480px and filled
the side bars by replicating edge pixels, which on a spiral would streak.
"""

import os
import struct
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))

import numpy as np
from PIL import Image, ImageFilter

import spiral as S
from wiilib import WAD
from zgx import APP_DIR, DONOR, EXTRACTED, OUT, SPLASH_DIR

SPLASH_SRC = os.path.join(SPLASH_DIR, "splash.png")
SPLASH_SIZE = (640, 480)
WIDE = 854                       # the 16:9 authoring width; 640/854 is the squash

SPLASH43 = (0x081700, 165683)
SPLASH169 = (0x0A9E40, 157270)
DOL_SIZE = 934656

ORIG_PATH = b"%s:/apps/fceugx/boot.dol"
NEW_PATH = f"%s:/apps/{APP_DIR}/boot.dol".encode()

# The splash's spiral is the same generator as the banner's but at a different
# scale; pitch fitted to splash.png at 99.8% of its solid-colour pixels.
SPLASH_PITCH = 11.02

# Colour counts to try, best first. Nothing here blurs or dithers: dithering
# would scatter noise across flat regions and cost more than it saves.
LADDER = [None, 32, 28, 24, 20, 16, 12, 10, 8, 6, 4]

TEXT_CORE = 200                  # L1 RGB distance that is unambiguously text
TEXT_SOFT = 40                   # below this, inside the text region, is background
TEXT_DILATE = 9                  # MaxFilter window: grows the core to cover its AA


def encode_png(im, limit, tag):
    """Smallest quality reduction that fits `limit`. Returns the PNG bytes."""
    src = os.path.join(OUT, f"_splash_src_{tag}.png")
    dst = os.path.join(OUT, f"_splash_{tag}.png")
    for colors in LADDER:
        q = im if colors is None else im.quantize(
            colors=colors, method=Image.MEDIANCUT, dither=Image.Dither.NONE).convert("RGB")
        q.save(src)
        subprocess.run(["magick", src, "-depth", "8",
                        "-define", "png:color-type=2",
                        "-define", "png:compression-level=9", "-strip", f"PNG24:{dst}"],
                       check=True, capture_output=True)
        b = open(dst, "rb").read()
        if len(b) <= limit:
            assert b[:8] == b"\x89PNG\r\n\x1a\n" and b[25] == 2, "not a colortype-2 PNG"
            assert struct.unpack(">II", b[16:24]) == SPLASH_SIZE, "wrong dimensions"
            print(f"    {tag}: {len(b):,} / {limit:,} bytes "
                  f"({'full colour' if colors is None else f'{colors} colours'})")
            return b
    raise RuntimeError(f"no setting fits {tag} into {limit} bytes")


def text_layer(src):
    """Lift 'LOADING...' off the spiral as RGBA, using the fitted spiral model."""
    ref = np.asarray(S.render(SPLASH_SIZE, pitch=SPLASH_PITCH), np.float32)
    obs = np.asarray(src, np.float32)
    dist = np.abs(obs - ref).sum(2)
    core = Image.fromarray(((dist >= TEXT_CORE) * 255).astype(np.uint8), "L")
    region = np.asarray(core.filter(ImageFilter.MaxFilter(TEXT_DILATE))) > 0
    soft = np.clip((dist - TEXT_SOFT) / (TEXT_CORE - TEXT_SOFT), 0.0, 1.0)
    alpha = np.where(region, soft, 0.0)
    print(f"    text layer: {(dist >= TEXT_CORE).sum():,} core px, "
          f"{(alpha > 0).sum():,} within the dilated region")
    return Image.fromarray(np.dstack([obs, alpha * 255]).astype(np.uint8), "RGBA")


def make_16_9(src):
    """Pre-squashed widescreen splash: elliptical spiral + resampled text."""
    k = SPLASH_SIZE[0] / WIDE
    out = S.render(SPLASH_SIZE, pitch=SPLASH_PITCH, xscale=k, levels=15).convert("RGBA")
    tw = round(SPLASH_SIZE[0] * k)
    text = text_layer(src).resize((tw, SPLASH_SIZE[1]), Image.LANCZOS)
    out.alpha_composite(text, ((SPLASH_SIZE[0] - tw) // 2, 0))
    return out.convert("RGB")


def main():
    d = bytearray(open(f"{EXTRACTED}/content2.app", "rb").read())
    assert len(d) == DOL_SIZE, f"donor forwarder is {len(d)}, expected {DOL_SIZE}"

    src = Image.open(SPLASH_SRC).convert("RGB")
    assert src.size == SPLASH_SIZE, f"splash.png is {src.size}, need {SPLASH_SIZE}"

    for (off, room), im, tag in ((SPLASH43, src, "4_3"),
                                 (SPLASH169, make_16_9(src), "16_9")):
        png = encode_png(im, room, tag)
        d[off:off + room] = png + b"\0" * (room - len(png))

    # ---- app path, in place
    at = d.find(ORIG_PATH)
    assert at >= 0, "original app path string not found in the donor forwarder"
    assert d.find(ORIG_PATH, at + 1) < 0, "app path string appears more than once"
    end = at + len(ORIG_PATH)
    while d[end] == 0:                      # the NUL plus any spare padding
        end += 1
    room = end - at
    assert len(NEW_PATH) + 1 <= room, (
        f"{NEW_PATH!r} needs {len(NEW_PATH)+1} bytes but only {room} are free before "
        f"the next literal -- it would have to be relocated instead")
    d[at:end] = NEW_PATH + b"\0" * (room - len(NEW_PATH))
    print(f"  app path: {NEW_PATH.decode()!r} at 0x{at:x} "
          f"({len(NEW_PATH)+1} of {room} bytes, patched in place)")

    # ---- prove this patch is data-only
    #
    # Every change above lands in data: the two splash regions and one string
    # literal. So the whole .text section -- which includes the app-path lis/addi
    # pair at 0x8124b4b0/0x8124b4c0 and the command-line block at 0x8124b5ac that
    # the previous project had to rewrite -- must still be byte-identical to
    # Tantric's. That is a stronger statement than checking the argv block alone,
    # and it is the reason no instruction-level reasoning is needed here.
    donor = WAD.load(DONOR).contents[2]
    TEXT = (0x100, 0x100 + 0x815E0)         # file offsets of .text (loads at 0x81230000)
    a, b = TEXT
    assert b <= SPLASH43[0], "the .text range overlaps the splash region"
    assert d[a:b] == donor[a:b], "code was modified; this patch must be data-only"
    assert at >= b, "the path string is inside .text?"
    assert len(d) == DOL_SIZE, f"size changed: {len(d)} != {DOL_SIZE}"
    print(f"  .text 0x{a:x}..0x{b:x} byte-identical to the donor (data-only patch)")

    os.makedirs(OUT, exist_ok=True)
    open(f"{OUT}/forwarder.app", "wb").write(bytes(d))
    print(f"  forwarder.app: {len(d):,} bytes (unchanged), boots sd:/apps/{APP_DIR}/boot.dol")
    print("  autoboot arguments: none (Tantric's one-argument path left intact)")


if __name__ == "__main__":
    main()
