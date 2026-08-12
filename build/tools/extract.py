"""Unpack the donor WAD so the builders have something to derive from.

The donor is Tantric's FCE Ultra GX, chosen for three reasons: its banner is the
smaller of his two (Snes9x GX's is 2.57 MB uncompressed against 1.39 MB), its
forwarder is the one whose patch offsets were reverse-engineered and proven on
the previous project, and its banner layout is byte-for-byte the same structure
as Snes9x GX's -- including the LogoPicture squash/stretch this channel wants.
So nothing is lost by not using the Snes9x WAD as donor.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from wiilib import U8, WAD, imd5_unwrap, unpack_lz77_imd5
from zgx import DONOR, EXTRACTED


def main():
    assert os.path.exists(DONOR), (
        f"donor WAD missing: {DONOR}\n"
        "Copy 'FCE Ultra GX - FCEU [Tantric].wad' into donor/.")
    w = WAD.load(DONOR)
    os.makedirs(EXTRACTED, exist_ok=True)
    for i, c in enumerate(w.contents):
        open(f"{EXTRACTED}/content{i}.app", "wb").write(c)

    app = w.contents[0]
    cut = app.find(b"\x55\xAA\x38\x2D")
    open(f"{EXTRACTED}/imet_prefix.bin", "wb").write(app[:cut])
    u8 = U8.load(app[cut:])

    for which in ("icon", "banner", "sound"):
        raw = u8.get(f"meta/{which}.bin")
        open(f"{EXTRACTED}/{which}.bin", "wb").write(raw)
        if which == "sound":
            open(f"{EXTRACTED}/sound.bns", "wb").write(imd5_unwrap(raw))
            continue
        dec = unpack_lz77_imd5(raw)
        open(f"{EXTRACTED}/{which}_u8.bin", "wb").write(dec)
        arc = U8.load(dec)
        d = f"{EXTRACTED}/{which}"
        os.makedirs(d, exist_ok=True)
        for i, p in arc.paths():
            if not arc.nodes[i].is_dir:
                open(os.path.join(d, os.path.basename(p)), "wb").write(arc.nodes[i].data)
        print(f"  {which}: {len(dec):,} bytes uncompressed")
    print(f"  forwarder: {len(w.contents[2]):,} bytes (content 2)")


if __name__ == "__main__":
    main()
