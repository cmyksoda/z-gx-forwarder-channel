"""Render what the Wii will actually show, from the built archives.

This is a real (if small) brlyt/brlan interpreter: it reads the finished
icon.bin / banner.bin back out of build/out, rips the layout and animations with
Benzin, decodes the TPLs that are really in there, and composites the panes frame
by frame. Nothing about the animation is re-described here -- if a keyframe is
wrong in the WAD, it is wrong in the preview too, which is the point.

Interpolation matches GX. Each keyframe carries a value and a tangent, and a
segment is a cubic Hermite:

    v(s) = v0(2s^3-3s^2+1) + v1(-2s^3+3s^2) + h*t0(s^3-2s^2+s) + h*t1(s^3-s^2)

so zero tangents give a smoothstep and slope-valued tangents give a straight
line. Outside the keyframe range the value holds.

Outputs, into build/out:
    icon_preview.gif     banner_start.gif     banner_loop.gif
    icon_frames.png      banner_frames.png    (contact sheets, 4:3 box marked)
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))

from PIL import Image, ImageDraw

import tpl as T
from wiilib import U8, unpack_lz77_imd5
from zgx import (BANNER_43, BANNER_ART, BANNER_FRAMES, BENZIN, ICON_43, ICON_ART,
                 ICON_FRAMES, OUT, benzin)

TAGBLOCK = r'<tag type="(\w+)"((?:[^>]*[^/>])?)>(.*?)</tag>'
CHANNELS = {"X Translation": "tx", "Y Translation": "ty", "Z Rotate": "rz",
            "X Scale": "sx", "Y Scale": "sy"}


# ------------------------------------------------------------------ animation

def hermite(keys, t):
    if not keys:
        return None
    if t <= keys[0][0]:
        return keys[0][1]
    if t >= keys[-1][0]:
        return keys[-1][1]
    for (f0, v0, m0), (f1, v1, m1) in zip(keys, keys[1:]):
        if f0 <= t <= f1:
            h = f1 - f0
            if h == 0:
                return v1
            s = (t - f0) / h
            return (v0 * (2*s**3 - 3*s**2 + 1) + v1 * (-2*s**3 + 3*s**2)
                    + h * m0 * (s**3 - 2*s**2 + s) + h * m1 * (s**3 - s**2))
    return keys[-1][1]


def parse_anim(xml):
    """{pane: {'tx': keys, ..., 'alpha': keys}} for pane-target tracks only."""
    out = {}
    for m in re.finditer(r'<pane name="([^"]+)" type="(\d)">(.*?)</pane>', xml, re.S):
        name, kind, body = m.group(1), m.group(2), m.group(3)
        if kind != "0":
            continue                                  # material tracks: nothing to draw
        tracks = out.setdefault(name, {})
        for tag in re.finditer(TAGBLOCK, body, re.S):
            ttype, _a, tbody = tag.groups()
            if ttype not in ("RLPA", "RLVC"):
                continue
            for e in re.finditer(r'<entry type1="\d+" type2="([^"]+)">(.*?)</entry>',
                                 tbody, re.S):
                ch = e.group(1)
                key = CHANNELS.get(ch) or ("alpha" if ttype == "RLVC" and ch == "16"
                                           else None)
                if not key:
                    continue
                tracks[key] = [(float(f), float(v), float(b)) for f, v, b in re.findall(
                    r"<frame>([-\d.]+)</frame>\s*<value>([-\d.]+)</value>"
                    r"\s*<blend>([-\d.]+)</blend>", e.group(2))]
    return out


# --------------------------------------------------------------------- layout

def parse_layout(xml):
    """Flat pane list in draw order, with parent links resolved from pas1/pae1."""
    panes, stack = [], []
    for m in re.finditer(r'<tag type="(\w+)"((?:[^>]*[^/>])?)(?:>(.*?)</tag>|\s*/>)',
                         xml, re.S):
        kind, attrs, body = m.group(1), m.group(2), m.group(3)
        if kind == "pas1":
            stack.append(len(panes) - 1)
            continue
        if kind == "pae1":
            stack.pop()
            continue
        if kind not in ("pan1", "pic1", "txt1", "wnd1") or body is None:
            continue
        g = lambda t, d="0": (re.search(rf"<{t}>([^<]*)</{t}>", body) or [None, d])[1] \
            if re.search(rf"<{t}>([^<]*)</{t}>", body) else d
        tr = re.search(r"<translate>\s*<x>([-\d.]+)</x>\s*<y>([-\d.]+)</y>", body)
        sc = re.search(r"<scale>\s*<x>([-\d.]+)</x>\s*<y>([-\d.]+)</y>", body)
        ro = re.search(r"<rotate>.*?<z>([-\d.]+)</z>", body, re.S)
        mat = re.search(r'<material name="([^"]+)"', body)
        panes.append(dict(
            kind=kind, name=re.search(r'name="([^"]*)"', attrs).group(1),
            parent=stack[-1] if stack else None,
            visible=g("visible", "01") == "01", alpha=int(g("alpha", "ff"), 16),
            tx=float(tr.group(1)), ty=float(tr.group(2)),
            sx=float(sc.group(1)) if sc else 1.0, sy=float(sc.group(2)) if sc else 1.0,
            rz=float(ro.group(1)) if ro else 0.0,
            w=float(g("width", "0")), h=float(g("height", "0")),
            mat=mat.group(1) if mat else None))
    return panes


def textures_by_material(xml, arc):
    """material name -> decoded RGBA texture (its first texture reference)."""
    out = {}
    for m in re.finditer(r'<entries name="([^"]+)">(.*?)</entries>', xml, re.S):
        t = re.search(r'<texture name="([^"]+)"', m.group(2))
        if not t:
            continue
        data = arc.nodes[arc.find(f"/arc/timg/{t.group(1)}")].data
        info = T.parse(data)[0]
        try:
            out[m.group(1)] = T.decode(data[info["data_off"]:], info["w"], info["h"],
                                       info["fmt"], info["pal"]).convert("RGBA")
        except NotImplementedError as e:
            # tpl.py decodes the formats this project emits. The donor also uses
            # IA4 for one texture we stub out, so skip rather than die -- but say
            # so, since a silently missing texture would be a confusing preview.
            print(f"    [skip] {t.group(1)}: no decoder for {e}")
    return out


# -------------------------------------------------------------------- compose

def render_frame(panes, tex, anim, frame, canvas):
    W, H = canvas
    img = Image.new("RGBA", canvas, (0, 0, 0, 255))
    for i, p in enumerate(panes):
        if not p["visible"]:
            continue
        # accumulate the ancestor chain (translation, alpha; parents here never
        # scale or rotate, which is why this stays a simple sum)
        x, y, a = 0.0, 0.0, 1.0
        j = i
        while j is not None:
            q = panes[j]
            tr = anim.get(q["name"], {})
            x += hermite(tr.get("tx"), frame) if "tx" in tr else q["tx"]
            y += hermite(tr.get("ty"), frame) if "ty" in tr else q["ty"]
            al = hermite(tr.get("alpha"), frame) if "alpha" in tr else q["alpha"]
            a *= max(0.0, min(255.0, al)) / 255.0
            j = q["parent"]
        if p["kind"] != "pic1" or a <= 0.002:
            continue
        t = tex.get(p["mat"])
        if t is None:
            continue
        tr = anim.get(p["name"], {})
        sx = hermite(tr.get("sx"), frame) if "sx" in tr else p["sx"]
        sy = hermite(tr.get("sy"), frame) if "sy" in tr else p["sy"]
        rz = hermite(tr.get("rz"), frame) if "rz" in tr else p["rz"]
        w, h = max(1, round(p["w"] * sx)), max(1, round(p["h"] * sy))
        spr = t.resize((w, h), Image.LANCZOS)
        if abs(rz) > 1e-6:
            # brlyt +y is up, so a positive Z rotation reads counter-clockwise on
            # screen -- which is exactly PIL's rotate() convention.
            spr = spr.rotate(rz, resample=Image.BICUBIC, expand=True)
        if a < 0.999:
            al = spr.getchannel("A").point(lambda v: round(v * a))
            spr.putalpha(al)
        # pane centre -> screen, flipping y
        cx, cy = W / 2.0 + x, H / 2.0 - y
        img.alpha_composite(spr, (round(cx - spr.width / 2), round(cy - spr.height / 2)))
    return img.convert("RGB")


def load(kind):
    arc = U8.load(unpack_lz77_imd5(open(f"{OUT}/{kind}.bin", "rb").read()))
    open(f"{BENZIN}/pv_{kind}.brlyt", "wb").write(arc.get(f"/arc/blyt/{kind}.brlyt"))
    benzin("r", f"pv_{kind}.brlyt", f"pv_{kind}.xmlyt")
    lyt = open(f"{BENZIN}/pv_{kind}.xmlyt").read()
    anims = {}
    for i, p in arc.paths():
        if p.endswith(".brlan"):
            stem = os.path.basename(p)[:-6]
            open(f"{BENZIN}/pv_{stem}.brlan", "wb").write(arc.get(p))
            benzin("r", f"pv_{stem}.brlan", f"pv_{stem}.xmlan")
            anims[stem] = parse_anim(open(f"{BENZIN}/pv_{stem}.xmlan").read())
    return parse_layout(lyt), textures_by_material(lyt, arc), anims


def sheet(frames, labels, safe, path, cols=4, zoom=1):
    """Contact sheet with the 4:3 safe area outlined on every tile."""
    w, h = frames[0].size
    rows = (len(frames) + cols - 1) // cols
    pad, top = 6, 14
    out = Image.new("RGB", (cols * (w * zoom + pad) + pad,
                            rows * (h * zoom + pad + top) + pad), (24, 24, 28))
    d = ImageDraw.Draw(out)
    for i, (f, lab) in enumerate(zip(frames, labels)):
        cx, cy = i % cols, i // cols
        ox = pad + cx * (w * zoom + pad)
        oy = pad + cy * (h * zoom + pad + top) + top
        im = f.resize((w * zoom, h * zoom), Image.NEAREST) if zoom > 1 else f
        out.paste(im, (ox, oy))
        sw, sh = safe
        d.rectangle([ox + (w * zoom - sw * zoom) // 2, oy + (h * zoom - sh * zoom) // 2,
                     ox + (w * zoom + sw * zoom) // 2 - 1,
                     oy + (h * zoom + sh * zoom) // 2 - 1], outline=(0, 255, 170))
        d.text((ox, oy - 11), lab, fill=(210, 210, 215))
    out.save(path)
    return path


def main():
    os.makedirs(OUT, exist_ok=True)

    # ------------------------------------------------------------------ icon
    panes, tex, anims = load("icon")
    anim = anims["icon"]
    step = 8
    frames = [render_frame(panes, tex, anim, f, ICON_ART)
              for f in range(0, ICON_FRAMES, step)]
    frames[0].save(f"{OUT}/icon_preview.gif", save_all=True, append_images=frames[1:],
                   duration=int(1000 * step / 60), loop=0, optimize=True)
    # 0 invisible, 120 fully up, 240 end of the hold, 360 back to 0
    keys = [0, 60, 120, 180, 240, 300, 360, 540]
    sheet([render_frame(panes, tex, anim, f, ICON_ART) for f in keys],
          [f"f{f} ({f/60:.1f}s)" for f in keys], ICON_43,
          f"{OUT}/icon_frames.png", cols=4, zoom=2)
    print(f"  icon_preview.gif  {len(frames)} frames @ {60/step:.0f}fps "
          f"({ICON_FRAMES/60:.1f}s loop)")

    # ---------------------------------------------------------------- banner
    panes, tex, anims = load("banner")
    for name, span, st in (("banner_Start", 300, 3), ("banner_Loop", BANNER_FRAMES, 10)):
        a = anims[name]
        fr = [render_frame(panes, tex, a, f, BANNER_ART) for f in range(0, span, st)]
        fr = [f.resize((f.width // 2, f.height // 2), Image.LANCZOS) for f in fr]
        out = f"{OUT}/{name.replace('banner_', 'banner_').lower()}.gif"
        fr[0].save(out, save_all=True, append_images=fr[1:],
                   duration=int(1000 * st / 60), loop=0, optimize=True)
        print(f"  {os.path.basename(out)}  {len(fr)} frames (frames 0..{span})")
    keys = [0, 15, 30, 60, 90, 110, 120, 126, 132, 200, 500, 900]
    sheet([render_frame(panes, tex, anims["banner_Start"], f, BANNER_ART) for f in keys],
          [f"f{f} ({f/60:.2f}s)" for f in keys], BANNER_43,
          f"{OUT}/banner_frames.png", cols=4)
    print(f"  banner_frames.png / icon_frames.png  (4:3 safe area outlined)")


if __name__ == "__main__":
    main()
