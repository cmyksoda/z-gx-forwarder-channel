"""Emit and edit Benzin's brlan XML (`.xmlan`).

A brlan is a list of animated panes; each pane holds tags (RLPA pane transform,
RLVC vertex/pane colour, RLTS texture SRT, RLTP texture swap), each tag holds
entries selecting one channel, each entry a list of keyframe triplets.

Two things about the format are worth stating plainly, because both were
established by round-tripping Tantric's own files rather than guessed:

* `<blend>` is the **tangent** -- the slope in value units per frame, not a
  weight. Leaving it 0 makes GX interpolate a segment as a smoothstep, which is
  what gives his fades and pops their soft ease. Setting it to the segment's own
  slope makes the segment perfectly linear instead; his background scroll does
  exactly that (`0:0/t0.002  1000:2/t0.002`, and 2/1000 = 0.002). A constant-
  speed rotation *must* be linear, or it visibly stalls at the loop seam.

* `type2` is a name for RLPA channels ("X Translation", "Z Rotate", ...) but a
  number for RLVC (16 = pane alpha). That asymmetry is Benzin's, and re-making
  an unmodified rip reproduces the original brlan byte for byte, so it is
  faithfully what the format wants.
"""

import re

# RLPA channels, spelled the way Benzin writes them
X_TRANS, Y_TRANS, Z_TRANS = "X Translation", "Y Translation", "Z Translation"
X_ROT, Y_ROT, Z_ROT = "X Rotate", "Y Rotate", "Z Rotate"
X_SCALE, Y_SCALE = "X Scale", "Y Scale"
PANE_ALPHA = "16"                       # RLVC


def linear(pts):
    """Keyframes with each tangent set to its segment slope -> constant speed."""
    out = []
    for i, (f, v) in enumerate(pts):
        j = min(i + 1, len(pts) - 1)
        k = max(i - 1, 0)
        df = pts[j][0] - pts[k][0]
        out.append((f, v, (pts[j][1] - pts[k][1]) / df if df else 0.0))
    return out


def smooth(pts):
    """Keyframes with zero tangents -> each segment eases in and out."""
    return [(f, v, 0.0) for f, v in pts]


def entry(channel, keys, type1=0):
    L = [f'\t\t\t\t\t\t<entry type1="{type1}" type2="{channel}">']
    for f, v, t in keys:
        L += ['\t\t\t\t\t\t\t<triplet>',
              f'\t\t\t\t\t\t\t\t<frame>{f:.15f}</frame>',
              f'\t\t\t\t\t\t\t\t<value>{v:.15f}</value>',
              f'\t\t\t\t\t\t\t\t<blend>{t:.15f}</blend>',
              '\t\t\t\t\t\t\t</triplet>']
    L.append('\t\t\t\t\t\t</entry>')
    return L


def pane(name, tags, kind=0):
    """kind 0 = pane animation target, 1 = material animation target."""
    L = [f'\t\t\t\t<pane name="{name}" type="{kind}">']
    for tag, entries in tags:
        L.append(f'\t\t\t\t\t<tag type="{tag}">')
        for channel, keys in entries:
            L += entry(channel, keys)
        L.append('\t\t\t\t\t</tag>')
    L.append('\t\t\t\t</pane>')
    return "\n".join(L)


def document(framesize, panes, loop=True):
    """A complete .xmlan from scratch, for when rewriting beats patching."""
    return "\n".join([
        '<?xml version="1.0" encoding="utf-8"?>',
        '\t\t<xmlan version="2.1.12BETA" brlan_version="0008">',
        f'\t\t\t<pai1 framesize="{framesize}" flags="{"01" if loop else "00"}">',
        *panes,
        '\t\t\t</pai1>',
        '\t\t</xmlan>',
    ]) + "\n"


def drop_panes(xml, names):
    """Remove whole <pane> blocks, so the panes fall back to their brlyt values.

    Used to delete the donor's tracks for panes we re-animate, and to delete his
    RLTP texture-swap tracks: those cycle a material between sprite frames, and
    a repurposed pane whose other frames are now 4x4 stubs would flicker to
    nothing several times a second.
    """
    for n in names:
        xml, k = re.subn(rf'\n?\t*<pane name="{re.escape(n)}" type="\d">.*?</pane>',
                         "", xml, flags=re.S)
        if not k:
            raise KeyError(f"no <pane name={n!r}> in brlan")
    return xml


def add_panes(xml, blocks):
    """Insert emitted <pane> blocks just before </pai1>."""
    assert "</pai1>" in xml, "not a brlan XML document"
    return xml.replace("</pai1>", "\n".join(blocks) + "\n\t\t\t</pai1>")


def pane_names(xml):
    return re.findall(r'<pane name="([^"]+)" type="\d">', xml)
