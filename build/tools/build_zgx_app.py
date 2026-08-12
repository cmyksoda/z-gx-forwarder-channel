"""Stage an SD-card-ready tree for Z-GX itself, next to the channel WAD.

Upstream (https://github.com/hotker79/Z-GX) ships no prebuilt binary and no
`apps/ZGX` folder, so the Homebrew Channel metadata and icon do not exist
anywhere to copy -- they are generated here. Keeping them in a build script
rather than as hand-made files in build/out matters: build/out is wiped by a
clean rebuild, and one-off files there silently disappear.

`boot.dol` is copied in if a Z-GX build is found. Set ZGX_DOL to point at one;
the default is the shadow-prefix build location documented in BUILDING.md. If it
is missing, everything else is still staged and the script says so rather than
failing, because the channel WAD does not depend on it.
"""

import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(__file__))

from PIL import Image

import spiral as S
from zgx import APP_DIR, BANNER_DIR, OUT, ROOT, TITLE, WAD_NAME

DOL = os.environ.get(
    "ZGX_DOL", os.path.expanduser("~/.cache/zgx-build/zgx-src/seta-gx.dol"))
STAGE = os.path.join(OUT, "sdcard")
HBC_ICON = (128, 48)             # the size the Homebrew Channel expects

# Pure ASCII and well-formed, both deliberately: the Homebrew Channel does not
# report a parse error, it silently falls back to the directory name and "no
# description available". A bare '&' did exactly that on the previous project.
META = """<?xml version="1.0" encoding="UTF-8"?>
<app version="1">
  <name>Z-GX</name>
  <coder>CheloRetro, Evoca (fadedled), Yabause Team</coder>
  <version>1.0</version>
  <release_date>20260812</release_date>
  <short_description>Sega Saturn emulator</short_description>
  <long_description>Experimental Sega Saturn emulator. Z-GX is CheloRetro's fork of Seta GX by Evoca (fadedled), itself a heavily modified port of Yabause, with SCU emulation and CHD support from devmiyax's Yaba Sanshiro. Video acceleration uses the Hollywood GPU.

Put games in sd:/ZGX/games, the BIOS at sd:/ZGX/bios/bios.bin, saves in sd:/ZGX/saves and cover art in sd:/ZGX/art. The BIOS is not included and is required.

Licensed under GNU GPL v2. This is an experimental project and is not polished for stability; bugs are expected.</long_description>
</app>
"""

README = """Z-GX -- copy to SD card root
============================

Copy the CONTENTS of this folder to the root of your SD card, so you end up with:

    sd:/apps/ZGX/boot.dol
    sd:/apps/ZGX/meta.xml
    sd:/apps/ZGX/icon.png
    sd:/ZGX/games/           <- .chd or .cue (subfolders allowed)
    sd:/ZGX/bios/bios.bin    <- REQUIRED. Not included (Sega copyright).
    sd:/ZGX/saves/
    sd:/ZGX/art/             <- cover PNGs, 128x192, named exactly as the game

"{wad}" does NOT go on the SD card -- install it with a WAD
manager. It needs a trucha-patched IOS, like any fakesigned channel.

Notes for testing
-----------------
* Be patient. The author's own notes (NOTAS/IDLE_DETECTION_OK.md) say the Saturn
  BIOS takes about 10 seconds to load. Several seconds of blank screen is
  expected, not a failure.
* 240p mode for CRTs toggles in-emulator with Z+Y, which creates or removes
  sd:/ZGX/240p.txt. None is shipped here, so you start in normal 480i.
* boot.dol is built from https://github.com/hotker79/Z-GX (GPL v2). meta.xml and
  icon.png are NOT from upstream -- it ships no apps/ZGX folder, so they were
  written for this project. Replace them if the author publishes real ones.
"""


def make_icon(path):
    """logo.png over a spiral, at the Homebrew Channel's 128x48."""
    w, h = HBC_ICON
    bg = S.render((w, h), pitch=6.0, levels=15).convert("RGBA")
    logo = Image.open(os.path.join(BANNER_DIR, "logo.png")).convert("RGBA")
    m = 4
    sc = min((w - 2 * m) / logo.width, (h - 2 * m) / logo.height)
    small = logo.resize((max(1, round(logo.width * sc)),
                         max(1, round(logo.height * sc))), Image.LANCZOS)
    bg.alpha_composite(small, ((w - small.width) // 2, (h - small.height) // 2))
    bg.convert("RGB").save(path)
    return small.size


def main():
    app = os.path.join(STAGE, "apps", APP_DIR)
    if os.path.isdir(STAGE):
        shutil.rmtree(STAGE)
    os.makedirs(app)
    for d in ("games", "bios", "saves", "art"):
        os.makedirs(os.path.join(STAGE, APP_DIR, d))

    open(os.path.join(app, "meta.xml"), "w").write(META)
    size = make_icon(os.path.join(app, "icon.png"))
    open(os.path.join(STAGE, "READ-ME-FIRST.txt"), "w").write(
        README.format(wad=WAD_NAME))

    wad = os.path.join(ROOT, WAD_NAME)
    if os.path.exists(wad):
        shutil.copy2(wad, STAGE)

    print(f"  staged {STAGE}")
    print(f"  meta.xml ({TITLE}), icon.png {HBC_ICON[0]}x{HBC_ICON[1]} "
          f"(logo at {size[0]}x{size[1]})")
    if os.path.exists(DOL):
        shutil.copy2(DOL, os.path.join(app, "boot.dol"))
        print(f"  boot.dol {os.path.getsize(DOL):,} bytes from {DOL}")
    else:
        print(f"  [note] no Z-GX build at {DOL} -- boot.dol not staged.")
        print("         Build it per BUILDING.md, or set ZGX_DOL to point at one.")


if __name__ == "__main__":
    main()
