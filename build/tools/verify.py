"""Pre-install verification. Reads the finished WAD back off disk and re-derives
everything from it, so nothing here trusts the builders.

It checks the two failure modes that are known to be unrecoverable-ish (the
icon's hard size cap and U8 directory parent indices, which is what caught a
System Menu brick on the previous project), the one that no structural check
catches (banner memory), and then the things specific to this channel: that the
spinning background actually covers the frame at every angle, that every sprite
stays inside the 4:3 safe area *including while it animates*, and that the
forwarder patch touched no code.

A note on one inherited check that is deliberately **not** reproduced. The
previous project's verify.py asserted every visible pane matched exactly
128x96 / 608x456. Those are 4:3-only truths: the Wii shows 4/3 more horizontal
layout units in widescreen (170.67 / 810.67), so art authored to fill widescreen
correctly would fail that assertion. It is replaced below by a rule that admits
both kinds of pane -- full-bleed layers that must cover the *widescreen* extent,
and sprites that must sit inside the *4:3* extent -- which is what
Icon_Sizing.md actually concluded.
"""

import hashlib
import os
import re
import struct
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))

import brlyt as BL
import preview as PV
import tpl as T
from wiilib import U8, WAD, imd5_unwrap, imet_titles, imet_verify, unpack_lz77_imd5
from zgx import (APP_DIR, BANNER_43, BANNER_ART, BANNER_FRAMES, BANNER_TURNS,
                 BENZIN, DONOR, ICON_43, ICON_ART, ICON_FRAMES, ICON_TURNS,
                 SPIRAL_TEXEL_SCALE, TITLE, TITLE_ID)

# Banner memory is shared across EVERY installed channel, uncompressed, and
# exceeding the total slows and then hard-freezes the Wii Menu while paging the
# channel grid with +/-. Comparing against a single channel's banner (FCEUGX's
# 1,388,896) is the wrong test and passed a 839 KB banner that helped tip a real
# system over: 6 channels installed came to 8.53 MB, of which Snes9x GX and
# mGBA GX were 2.57 MB each. So this budget is a strict *self-imposed* share.
# A share, not a limit: roughly a sixth of the system-wide headroom, so several
# channels of this size coexist. Do not re-derive it from whatever is installed
# today -- LSD Dream Emulator was 592,160 when this was written and has since
# been rebuilt at 796,448, so "under LSD's" was a moving target.
BANNER_BUDGET = 600000
FCEUGX_BANNER = 1388896          # kept for context in the printout
ICON_CAP = 0x19000               # 102,400 -- a HARD System Menu check, not a budget
DOL_SIZE = 934656

# 4:3 extent, and the widescreen extent the Menu reveals (4/3 wider -- see
# Icon_Sizing.md). Height never changes; only width.
GEOM = {"icon": (ICON_ART, ICON_43), "banner": (BANNER_ART, BANNER_43)}
ANIM_OF = {"icon": ["icon"], "banner": ["banner_Start", "banner_Loop"]}
SPRITE_PANES = {"icon": {"Logo00Picture"},
                "banner": {"ControllerPicture", "LogoPicture"}}
BLEED_PANES = {"icon": {"BackgroundPicture"}, "banner": {"BackgroundPicture"}}
TURNS = {"icon": ICON_TURNS, "banner": BANNER_TURNS}
SPINNER = "BackgroundPicture"

# System titles and every homebrew channel ID we know of, so a collision cannot
# quietly overwrite something already installed.
RESERVED = {b"HAEA", b"HABA", b"HACA", b"HAFA", b"HAAA", b"HABK", b"HCZA",
            b"HAYA", b"HAZA", b"HAXX", b"JODI", b"DUTB", b"LULZ", b"1234",
            b"FCEU", b"9XGX", b"VBAG", b"GBGX", b"WIIM", b"SNES", b"LSDE"}

ok = True


def check(cond, label, detail=""):
    global ok
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}" + (f"  {detail}" if detail else ""))
    if not cond:
        ok = False
    return cond


warnings = []


def warn(cond, label, detail=""):
    """For things that are a framing judgement, not a defect.

    4:3 cropping is the case in point: art a few pixels outside the 4:3 box still
    installs and runs perfectly and looks right in widescreen, so it must not fail
    the build -- but it is silently invisible to 4:3 users, so it must not be
    silent either.
    """
    print(f"  [{'PASS' if cond else 'WARN'}] {label}" + (f"  {detail}" if detail else ""))
    if not cond:
        warnings.append(f"{label}: {detail}")
    return cond


def benzin_rip(data, stem, ext):
    src = os.path.join(BENZIN, f"vfy_{stem}.{ext}")
    dst = os.path.join(BENZIN, f"vfy_{stem}.xml{ext[2:]}")
    open(src, "wb").write(data)
    subprocess.run(["wine", "BENZIN.EXE", "r", os.path.basename(src),
                    os.path.basename(dst)], cwd=BENZIN, capture_output=True,
                   env={**os.environ, "WINEDEBUG": "-all"})
    return open(dst, errors="replace").read()


def sections(d):
    """Section magics of a brlyt/brlan, in order."""
    hlen, n = struct.unpack(">HH", d[12:16])
    out, o = [], hlen
    for _ in range(n):
        out.append(d[o:o + 4].decode("ascii", "replace"))
        o += struct.unpack(">I", d[o + 4:o + 8])[0]
    return out


def track_range(keys, frames):
    """(min, max) of a Hermite track sampled across the whole animation."""
    vals = [PV.hermite(keys, f) for f in range(0, frames + 1)]
    return min(vals), max(vals)


def check_geometry(kind, lyt, anims, arc):
    """Widescreen-aware framing, replacing the old fixed-viewport assertion."""
    art, safe = GEOM[kind]
    wide_w = safe[0] * 4.0 / 3.0                 # the Menu reveals 4/3 more width
    print(f"\n-- {kind} framing  (4:3 {safe[0]:.0f}x{safe[1]}, "
          f"16:9 {wide_w:.2f}x{safe[1]}, authored {art[0]}x{art[1]})")

    vis = BL.visible_pictures(lyt)
    check(bool(vis), "at least one visible picture pane", f"{len(vis)} visible")
    for name, size, tr, alpha, mat in vis:
        expected_bleed = name in BLEED_PANES[kind]
        if expected_bleed:
            check(size[0] >= wide_w - 0.01 and size[1] >= safe[1] - 0.01,
                  f"{name} covers the widescreen extent (full-bleed layer)",
                  f"{size[0]:.0f}x{size[1]:.0f}")
        else:
            check(name in SPRITE_PANES[kind], f"{name} is a known sprite pane")
        check(alpha == "ff", f"{name} rests at full alpha", alpha)

        # Sprites are stored 1:1 so the Wii never resamples them. The spinner is
        # the deliberate exception: a rotating square must cover the frame's
        # diagonal, so at 1:1 it stores 2.6x more texels than are ever visible,
        # and buying that back matters when banner memory is shared system-wide.
        tname = re.search(rf'<entries name="{mat}">.*?<texture name="([^"]+)"',
                          lyt, re.S)
        if tname:
            info = T.parse(arc.get(f"/arc/timg/{tname.group(1)}"))[0]
            if name == SPINNER and kind == "banner":
                got = info["w"] / size[0]
                check(info["w"] == info["h"] and abs(got - SPIRAL_TEXEL_SCALE) < 0.02,
                      f"{name}: texture density matches SPIRAL_TEXEL_SCALE",
                      f"tex {info['w']}x{info['h']} over pane {size[0]:.0f} "
                      f"= x{got:.2f}, configured x{SPIRAL_TEXEL_SCALE:g}")
            else:
                check((info["w"], info["h"]) == (int(size[0]), int(size[1])),
                      f"{name}: texture matches pane size 1:1 (no resampling)",
                      f"tex {info['w']}x{info['h']} vs pane {size[0]:.0f}x{size[1]:.0f}")

    # the spinner must cover the frame at EVERY angle: a pane rotates about its
    # centre, so its inscribed circle has to contain the widescreen rectangle
    spin = [v for v in vis if v[0] == SPINNER]
    if check(bool(spin), f"{SPINNER} exists and is visible"):
        size, at = spin[0][1], spin[0][2]
        # The pane may be lifted off centre (the banner's is, to clear the Menu's
        # title bar), so the radius has to reach the furthest frame corner FROM
        # THE PANE CENTRE -- not from the origin.
        need = ((wide_w / 2.0 + abs(at[0])) ** 2
                + (safe[1] / 2.0 + abs(at[1])) ** 2) ** 0.5
        check(size[0] == size[1], f"{SPINNER} is square (it rotates)",
              f"{size[0]:.0f}x{size[1]:.0f}")
        check(min(size) / 2.0 >= need,
              f"{SPINNER} inscribed circle covers the 16:9 frame at all angles",
              f"radius {min(size)/2:.1f} >= {need:.1f} needed "
              f"(pane centred at {at[0]:+.0f},{at[1]:+.0f})")

    # sprites must stay inside the 4:3 box for the WHOLE animation, not just at
    # rest -- an overshooting scale is exactly how a sprite gets clipped on a 4:3
    # TV for a few frames without anyone noticing in widescreen.
    frames = ICON_FRAMES if kind == "icon" else BANNER_FRAMES
    for aname in ANIM_OF[kind]:
        anim = anims[aname]
        panes = PV.parse_layout(lyt)
        by_name = {p["name"]: p for p in panes}
        for sname in sorted(SPRITE_PANES[kind]):
            p = by_name.get(sname)
            if not p:
                continue

            # accumulate ancestor translation extremes
            x0 = x1 = y0 = y1 = 0.0
            j = panes.index(p)
            while j is not None:
                q = panes[j]
                tr = anim.get(q["name"], {})
                for key, lo_hi in (("tx", "x"), ("ty", "y")):
                    if key in tr:
                        lo, hi = track_range(tr[key], frames)
                    else:
                        lo = hi = q[key]
                    if lo_hi == "x":
                        x0, x1 = x0 + lo, x1 + hi
                    else:
                        y0, y1 = y0 + lo, y1 + hi
                j = q["parent"]

            tr = anim.get(sname, {})
            sx = track_range(tr["sx"], frames)[1] if "sx" in tr else p["sx"]
            sy = track_range(tr["sy"], frames)[1] if "sy" in tr else p["sy"]
            hw, hh = p["w"] * sx / 2.0, p["h"] * sy / 2.0

            # the fly-in deliberately starts off-screen, so only the resting
            # end of the travel is checked for the x extent
            rest_x = PV.hermite(tr["tx"], frames) if "tx" in tr else p["tx"]
            jx = 0.0
            j = panes.index(p)
            while panes[j]["parent"] is not None:
                j = panes[j]["parent"]
                jx += panes[j]["tx"]
            L, R = jx + rest_x - hw, jx + rest_x + hw
            B, TOP = y0 - hh, y1 + hh
            inside = (L >= -safe[0]/2 - 0.01 and R <= safe[0]/2 + 0.01
                      and B >= -safe[1]/2 - 0.01 and TOP <= safe[1]/2 + 0.01)
            warn(inside, f"{aname}: {sname} stays inside the 4:3 safe area",
                  f"x {L:.1f}..{R:.1f} (limit +-{safe[0]/2:.0f}), "
                  f"y {B:.1f}..{TOP:.1f} (limit +-{safe[1]/2:.0f})")


def check_spin(kind, anims):
    """The rotation must be a whole number of turns and perfectly linear."""
    print(f"\n-- {kind} spin")
    frames = ICON_FRAMES if kind == "icon" else BANNER_FRAMES
    for aname in ANIM_OF[kind]:
        tr = anims[aname].get(SPINNER, {})
        if not check("rz" in tr, f"{aname}: {SPINNER} has a Z Rotate track"):
            continue
        keys = tr["rz"]
        total = keys[-1][1] - keys[0][1]
        turns = total / 360.0
        check(abs(turns - round(turns)) < 1e-6 and round(turns) != 0,
              f"{aname}: rotation is a whole number of turns (seamless wrap)",
              f"{total:+.1f} deg = {turns:+g} turns")
        check(abs(turns - TURNS[kind]) < 1e-6,
              f"{aname}: matches the configured {TURNS[kind]:+g} turns")
        check(keys[0][0] == 0 and keys[-1][0] == frames,
              f"{aname}: rotation spans the full {frames}-frame cycle",
              f"{keys[0][0]:.0f}..{keys[-1][0]:.0f}")
        slope = total / (keys[-1][0] - keys[0][0])
        check(all(abs(m - slope) < 1e-6 for _f, _v, m in keys),
              f"{aname}: tangents are linear, so the speed never wavers",
              f"slope {slope:+.4f} deg/frame ({abs(slope)*60:.1f} deg/s)")


def check_rest_values(anims, lyt):
    """Every Start track we wrote must finish on the value the layout holds.

    Then the Start -> Loop hand-off cannot jump, and neither can a Menu that
    rebinds panes from layout defaults. (The donor is not like this: its logo
    ends at -120 while its brlyt says 0, and it relies on pane state persisting.)

    Only *visible* panes are checked. Tantric's character-sprite panes still
    carry his own tracks, which end wherever his loop wants them; they are
    invisible here, so where they end is none of our business.
    """
    print("\n-- banner rest values")
    panes = {p["name"]: p for p in PV.parse_layout(lyt)}
    visible = {n for n, *_ in BL.visible_pictures(lyt)}
    for pane, chans in sorted(anims["banner_Start"].items()):
        p = panes.get(pane)
        if not p or pane not in visible:
            continue
        for ch, keys in sorted(chans.items()):
            if ch == "ty":                     # the idle bob returns to 0 by design
                continue
            end = PV.hermite(keys, BANNER_FRAMES)
            want = p.get(ch)
            if want is None:
                continue
            if ch == "rz":
                # a whole number of turns leaves the pane in the same orientation
                end, want = end % 360.0, want % 360.0
            check(abs(end - want) < 0.01,
                  f"{pane}.{ch} ends on the layout's own value"
                  + (" (mod 360)" if ch == "rz" else ""),
                  f"{end:.3f} vs brlyt {want:.3f}")


def installed_banner_report(ours):
    """Sum the banner memory of every channel installed in Dolphin's NAND.

    This is the constraint that actually bites, and no per-WAD check can see it.
    It is reported rather than enforced because it depends on what happens to be
    installed, not on this WAD -- but silence here is how a Menu freeze gets
    shipped.
    """
    nand = os.path.expanduser("~/.local/share/dolphin-emu/Wii/title/00010001")
    if not os.path.isdir(nand):
        return

    print("\n-- installed banner memory (Dolphin NAND, uncompressed)")
    total, rows = 0, []
    for tid in sorted(os.listdir(nand)):
        cdir = os.path.join(nand, tid, "content")
        if not os.path.isdir(cdir):
            continue
        for f in sorted(os.listdir(cdir)):
            if not f.endswith(".app"):
                continue
            d = open(os.path.join(cdir, f), "rb").read()
            if b"IMET" not in d[:0x800]:
                continue
            off, titles = imet_titles(d)
            banner = struct.unpack(">I", d[off + 0x10:off + 0x14])[0]
            names = [t for t in titles if t]
            rows.append((bytes.fromhex(tid).decode("ascii", "replace"),
                         names[0] if names else "?", banner))
            total += banner
            break

    installed_ours = next((b for t, _n, b in rows if t == TITLE_ID), None)
    for tid, name, banner in sorted(rows, key=lambda r: -r[2]):
        mark = "  <- this channel, as currently installed" if tid == TITLE_ID else ""
        print(f"  [info] {tid:6s} {name[:24]:24s} {banner:9,}{mark}")
    print(f"  [info] {'':6s} {'TOTAL':24s} {total:9,} ({total/1048576:.2f} MB) "
          f"across {len(rows)} channels")
    if installed_ours is not None and installed_ours != ours:
        after = total - installed_ours + ours
        print(f"  [info] {'':6s} {'after reinstalling this WAD':24s} {after:9,} "
              f"({after/1048576:.2f} MB, {(ours-installed_ours)/1024:+.0f} KB)")
        total = after

    # Name the worst offenders. Shrinking *this* channel cannot rescue a system
    # already over the line, and the first instinct is to keep squeezing the WAD
    # in front of you -- so point at where the memory actually is.
    if total > 6 * 1024 * 1024:
        big = [r for r in sorted(rows, key=lambda r: -r[2]) if r[2] > 1024 * 1024]
        if big:
            share = sum(b for _t, _n, b in big) / total * 100
            print(f"  [info] {'':6s} {'over 1 MB each':24s} "
                  + ", ".join(f"{n[:18]} {b/1048576:.2f} MB" for _t, n, b in big)
                  + f"  ({share:.0f}% of the total)")
    warn(total <= 6 * 1024 * 1024,
         "total installed banner memory is in safe territory",
         f"{total/1048576:.2f} MB -- the Menu freezes on +/- paging when this "
         f"grows too large; the biggest contributors dominate, not this channel")


def check_arc(arc, kind, donor):
    print(f"\n-- {kind}.bin internals")
    check(not arc.check_tree(), "U8 directory parent indices sane",
          str(arc.check_tree() or ""))

    # A minimal hand-built brlyt that omitted fnl1/grp1 bricked the System Menu
    # on the previous project, so the section list must match the working donor.
    p = f"/arc/blyt/{kind}.brlyt"
    ours, theirs = sections(arc.get(p)), sections(donor.get(p))
    check(ours == theirs, f"{kind}.brlyt section list matches donor",
          f"{len(ours)} sections" if ours == theirs
          else f"missing {[s for s in theirs if s not in ours]}")
    check("grp1" in ours, f"{kind}.brlyt has a grp1 root group")
    for i, ap in arc.paths():
        if ap.endswith(".brlan"):
            check(sections(arc.get(ap)) == sections(donor.get(ap)),
                  f"{os.path.basename(ap)} section list matches donor")

    files = {os.path.basename(q) for i, q in arc.paths() if not arc.nodes[i].is_dir}
    tpls = {f for f in files if f.endswith(".tpl")}
    lyt = benzin_rip(arc.get(p), f"{kind}_lyt", "brlyt")
    txl = re.findall(r"<name>([^<]+\.tpl)</name>", lyt)
    mats = set(re.findall(r'<entries name="([^"]+)"', lyt))
    panes = set(re.findall(r'<tag type="(?:pan1|pic1|txt1|wnd1)" name="([^"]*)"', lyt))
    check(set(txl) <= tpls, "every texture the layout names exists",
          f"missing {set(txl)-tpls}" if set(txl) - tpls else f"{len(txl)} textures")
    matrefs = set(re.findall(r'<material name="([^"]+)" />', lyt))
    check(matrefs <= mats, "every pane's material is defined",
          f"missing {matrefs-mats}" if matrefs - mats else f"{len(matrefs)} refs")

    # Pane names live in a fixed 16-byte field that spills into the 8-byte
    # userdata field. Tantric's own panes already do this and work, so only flag
    # overflows we introduced.
    spill = lambda t: {n for n, u in re.findall(
        r'<tag type="(?:pan1|pic1)" name="([^"]*)" userdata="([^"]*)"', t) if u}
    dlyt = benzin_rip(donor.get(p), f"{kind}_dlyt", "brlyt")
    new_spill = spill(lyt) - spill(dlyt)
    check(not new_spill, "no pane name we added overflows its 16-byte field",
          f"{sorted(new_spill)}" if new_spill else
          f"{len(spill(lyt))} inherited from donor")

    # Materials carrying our art must have an identity texture matrix and clamp:
    # BackgroundMaterial ships GX_MIRROR/GX_REPEAT with XScale 2.0 because
    # Tantric tiled a half-width texture, and inheriting that renders a
    # full-bleed image at half width, mirrored.
    shown = {m for _n, _s, _t, _a, m in BL.visible_pictures(lyt) if m}
    for m in re.finditer(r'<entries name="([^"]+)">(.*?)</entries>', lyt, re.S):
        if m.group(1) not in shown:
            continue
        b = m.group(2)
        wrap = re.search(r"<wrap_s>(\w+)</wrap_s>\s*<wrap_t>(\w+)</wrap_t>", b)
        srt = re.search(r"<XTrans>([-\d.]+)</XTrans>\s*<YTrans>([-\d.]+)</YTrans>"
                        r"\s*<Rotate>([-\d.]+)</Rotate>\s*<XScale>([-\d.]+)</XScale>"
                        r"\s*<YScale>([-\d.]+)</YScale>", b)
        check(wrap.group(1) == "GX_CLAMP" and wrap.group(2) == "GX_CLAMP",
              f"{m.group(1)} clamps (no tiling/mirroring)",
              f"{wrap.group(1)}/{wrap.group(2)}")
        vals = [float(srt.group(i)) for i in (1, 2, 3, 4, 5)]
        check(vals == [0.0, 0.0, 0.0, 1.0, 1.0],
              f"{m.group(1)} has an identity texture matrix",
              f"trans=({vals[0]},{vals[1]}) scale=({vals[3]},{vals[4]})")

    anims, ripped = {}, {}
    for i, ap in arc.paths():
        if not ap.endswith(".brlan"):
            continue
        stem = os.path.basename(ap)[:-6]
        an = benzin_rip(arc.get(ap), stem + "_an", "brlan")
        ripped[stem] = an
        anims[stem] = PV.parse_anim(an)
        apanes = set(re.findall(r'<pane name="([^"]+)" type="0"', an))
        amats = set(re.findall(r'<pane name="([^"]+)" type="1"', an))
        atimg = set(re.findall(r'<timg name="([^"]+)" />', an))
        check(apanes <= panes, f"{stem}: animated panes exist in layout",
              f"missing {apanes-panes}" if apanes - panes else f"{len(apanes)} panes")
        check(amats <= mats, f"{stem}: animated materials exist",
              f"missing {amats-mats}" if amats - mats else "none")
        check(atimg <= tpls, f"{stem}: RLTP swap textures exist",
              f"missing {atimg-tpls}" if atimg - tpls else "none")

    # An RLTP track on a material we repurposed would cycle our art away to a
    # 4x4 stub several times a second.
    for stem, an in ripped.items():
        bad = set()
        for m in re.finditer(r'<pane name="([^"]+)" type="1">(.*?)</pane>', an, re.S):
            if "RLTP" in m.group(2) and m.group(1) in shown:
                bad.add(m.group(1))
        check(not bad, f"{stem}: no RLTP texture-swap on a material we use",
              f"{sorted(bad)}" if bad else f"{len(shown)} materials in use")

    for i, q in arc.paths():
        if not q.endswith(".tpl"):
            continue
        for t in T.parse(arc.nodes[i].data):
            check(t["w"] % 4 == 0 and t["h"] % 4 == 0,
                  f"{os.path.basename(q)} dimensions 4-aligned",
                  f"{t['w']}x{t['h']} {T.NAMES[t['fmt']]}")
    return lyt, anims


def main():
    path = sys.argv[1]
    print(f"== {os.path.basename(path)}  ({os.path.getsize(path):,} bytes)")

    w = WAD.load(path)
    print("\n-- container")
    n = struct.unpack(">H", w.tmd[0x1DE:0x1E0])[0]
    for i, c in enumerate(w.contents):
        e = 0x1E4 + i * 36
        check(hashlib.sha1(c).digest() == w.tmd[e + 16:e + 36],
              f"content{i} SHA-1 matches TMD", f"{len(c):,} bytes")
    check(hashlib.sha1(w.tmd[0x140:]).digest()[0] == 0, "TMD is fakesigned (trucha)")
    check(hashlib.sha1(w.tik[0x140:]).digest()[0] == 0, "ticket is fakesigned (trucha)")
    tid = w.title_id
    check(tid[:4] == bytes.fromhex("00010001"), "title type is 0x00010001 (channel)")
    check(tid[4:] not in RESERVED, "channel ID unused by system/known homebrew",
          tid[4:].decode())
    check(w.tik[0x1DC:0x1E4] == tid, "ticket title ID matches TMD")
    boot = struct.unpack(">H", w.tmd[0x1E0:0x1E2])[0]
    check(boot == 1, "boot index points at the NAND loader stub", f"index {boot}")
    dw = WAD.load(DONOR)
    check(w.contents[1] == dw.contents[1],
          "content1 is Tantric's NAND loader stub, untouched",
          hashlib.sha1(w.contents[1]).hexdigest()[:16])
    ios = struct.unpack(">Q", w.tmd[0x184:0x18C])[0] & 0xFFFFFFFF
    print(f"  [info] boot IOS {ios}, {n} contents")

    print("\n-- banner archive (content 0)")
    app = w.contents[0]
    check(imet_verify(app), "IMET md5 valid")
    off, names = imet_titles(app)
    filled = [x for x in names if x]
    check(len(filled) == 10 and len(set(filled)) == 1,
          "all 10 language slots set", repr(filled[0]) if filled else "")
    check(filled and filled[0] == TITLE, "channel name", repr(filled[0]))
    u8 = U8.load(app[app.find(b"\x55\xAA\x38\x2D"):])
    check(not u8.check_tree(), "outer U8 tree sane")
    sizes = struct.unpack(">III", app[off + 0x0C:off + 0x18])
    parts = {k: u8.get(f"meta/{k}.bin") for k in ("icon", "banner", "sound")}
    actual = (len(unpack_lz77_imd5(parts["icon"])),
              len(unpack_lz77_imd5(parts["banner"])),
              len(imd5_unwrap(parts["sound"])))
    check(sizes == actual, "IMET sizes match the real payloads", f"{sizes}")
    check(actual[0] <= ICON_CAP, "icon within the System Menu's HARD 0x19000 cap",
          f"{actual[0]:,} / {ICON_CAP:,} ({actual[0]/ICON_CAP:.0%})")
    check(actual[1] <= BANNER_BUDGET,
          "banner within our strict share of Wii Menu banner memory",
          f"{actual[1]:,} / {BANNER_BUDGET:,} ({actual[1]/BANNER_BUDGET:.0%}; "
          f"{actual[1]/FCEUGX_BANNER:.0%} of FCEUGX's single banner)")
    installed_banner_report(actual[1])

    dapp = dw.contents[0]
    dono = U8.load(dapp[dapp.find(b"\x55\xAA\x38\x2D"):])
    for kind in ("icon", "banner"):
        arc = U8.load(unpack_lz77_imd5(parts[kind]))
        lyt, anims = check_arc(arc, kind,
                               U8.load(unpack_lz77_imd5(dono.get(f"meta/{kind}.bin"))))
        check_geometry(kind, lyt, anims, arc)
        check_spin(kind, anims)
        if kind == "banner":
            check_rest_values(anims, lyt)

    print("\n-- banner sound")
    b = imd5_unwrap(parts["sound"])
    check(b[:4] == b"BNS ", "BNS magic")
    check(struct.unpack(">I", b[8:12])[0] == len(b), "BNS fileSize matches")
    i = b.find(b"INFO")
    total = struct.unpack(">I", b[i + 20:i + 24])[0]
    dat = b.find(b"DATA")
    dsz = struct.unpack(">I", b[dat + 4:dat + 8])[0]
    rate = struct.unpack(">H", b[i + 12:i + 14])[0]
    check(b[i + 9] == 0, "loop flag off (audio.wav is a one-shot that fades out)")
    check(b[i + 8] == 0, "codec 0 (Nintendo DSP ADPCM)")
    check(b[i + 10] == 1, "mono")
    # 14 samples per 8-byte frame, with the final frame padded if the sample
    # count does not divide by 14 -- so the invariant is the frame count, not a
    # flat 1.75 ratio. (The previous project asserted exactly 1.75 and got away
    # with it only because that file's length happened to be a multiple of 14.
    # Tantric's own banner sound is not: 396,506 samples, ratio 1.749991.)
    frames_needed = -(-total // 14)
    check(dsz - 8 == frames_needed * 8,
          "DSP ADPCM frame count matches the sample count",
          f"{dsz-8:,} bytes = {frames_needed:,} frames x 8 "
          f"({total:,} samples, ratio {total/(dsz-8):.6f})")
    print(f"  [info] {total:,} samples @ {rate} Hz = {total/rate:.2f}s mono")

    print("\n-- forwarder (content 2)")
    d = w.contents[2]
    donor2 = dw.contents[2]
    check(len(d) == DOL_SIZE, "size unchanged from Tantric's", f"{len(d):,}")
    TEXT = (0x100, 0x100 + 0x815E0)
    check(d[TEXT[0]:TEXT[1]] == donor2[TEXT[0]:TEXT[1]],
          "no code modified -- the patch is data-only",
          f".text 0x{TEXT[0]:x}..0x{TEXT[1]:x}")
    want = f"%s:/apps/{APP_DIR}/boot.dol".encode()
    at = donor2.find(b"%s:/apps/fceugx/boot.dol")
    got = d[at:d.find(b"\0", at)]
    check(got == want, "app path string patched in place",
          f"{got.decode()!r} at 0x{at:x}")
    check(b"fceugx" not in d[at:at + 32], "old path fully overwritten")
    for name, (o, room) in (("4:3", (0x081700, 165683)), ("16:9", (0x0A9E40, 157270))):
        png = d[o:o + room]
        end = png.find(b"IEND") + 8
        check(png[:8] == b"\x89PNG\r\n\x1a\n" and png[25] == 2,
              f"{name} splash is a colortype-2 PNG (PNGU rejects palette PNGs)",
              f"{end:,} bytes used of {room:,}")
        wpx, hpx = struct.unpack(">II", png[16:24])
        check((wpx, hpx) == (640, 480), f"{name} splash is 640x480", f"{wpx}x{hpx}")

    if warnings:
        print(f"\n-- {len(warnings)} warning(s) (these install and run fine; they")
        print("   only affect what a 4:3 TV shows)")
        for w in warnings:
            print(f"   * {w}")
    print("\n" + ("== ALL CHECKS PASSED" if ok else "== FAILURES ABOVE"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
