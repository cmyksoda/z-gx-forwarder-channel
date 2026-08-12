"""Edit Benzin's brlyt XML (`.xmlyt`) with the smallest possible delta.

The layout is *derived from Tantric's donor*, never emitted from scratch. A
hand-built minimal brlyt bricked the System Menu on the previous project (black
screen after Health & Safety) because it omitted the `fnl1` and `grp1` sections,
which the Menu dereferences unconditionally. So: keep every section, keep every
pane, keep every name, and change only geometry, visibility and materials.

Keeping the donor's *names* is deliberate. Pane names live in a fixed 16-byte
field that silently spills into the following 8-byte `userdata` field, and every
name is cross-referenced from the material list, the texture list and both
brlans. Renaming buys readability and risks a dangling reference, so the
donor's names stay and the mapping is documented instead:

    banner  BackgroundPicture <- the spiral      ControllerPicture <- the console
            LogoPicture       <- the Z-GX logo
    icon    BackgroundPicture <- the spiral      Logo00Picture     <- the Z-GX logo
"""

import re

# Benzin writes self-closing <tag type="pas1" /> markers between panes. A naive
# `<tag ...>(.*?)</tag>` matches one of those and then swallows the whole next
# pane, so the attribute group must be forbidden from ending in '/'.
TAGBLOCK = r'<tag type="(\w+)"((?:[^>]*[^/>])?)>(.*?)</tag>'
PANE_KINDS = ("pan1", "pic1", "txt1", "wnd1")


def _set(body, tag, value):
    return re.sub(rf"<{tag}>[^<]*</{tag}>", f"<{tag}>{value}</{tag}>", body)


def _set_xy(body, group, x, y, z=None):
    if z is None:
        return re.sub(rf"(<{group}>\s*<x>)[^<]*(</x>\s*<y>)[^<]*(</y>)",
                      rf"\g<1>{x:.10f}\g<2>{y:.10f}\g<3>", body)
    return re.sub(rf"(<{group}>\s*<x>)[^<]*(</x>\s*<y>)[^<]*(</y>\s*<z>)[^<]*(</z>)",
                  rf"\g<1>{x:.10f}\g<2>{y:.10f}\g<3>{z:.10f}\g<4>", body)


def edit_panes(xml, spec, hide_others=True):
    """Apply `spec` -- {pane_name: {translate, size, scale, rotate, alpha}} --
    and set every other drawable pane invisible.

    Panes named in `spec` are forced visible at alpha ff unless the spec says
    otherwise. Forcing alpha matters: the donor icon's `Logo00Pane` ships
    alpha=b4 (180) and pane alpha multiplies down the tree, so inheriting it
    would cap its child at 70% and quietly flatten the fade.
    """
    seen = set()

    def fix(m):
        kind, attrs, body = m.groups()
        if kind not in PANE_KINDS:
            return m.group(0)
        nm = re.search(r'name="([^"]*)"', attrs)
        nm = nm.group(1) if nm else ""
        if nm == "RootPane":
            return m.group(0)
        if nm in spec:
            seen.add(nm)
            s = spec[nm]
            body = _set(body, "visible", "01")
            body = _set(body, "alpha", s.get("alpha", "ff"))
            if "translate" in s:
                body = _set_xy(body, "translate", *s["translate"], z=0.0)
            if "size" in s:
                w, h = s["size"]
                body = re.sub(r"(<size>\s*<width>)[^<]*(</width>\s*<height>)[^<]*(</height>)",
                              rf"\g<1>{w:f}\g<2>{h:f}\g<3>", body)
            body = _set_xy(body, "scale", *s.get("scale", (1.0, 1.0)))
            body = _set_xy(body, "rotate", *s.get("rotate", (0.0, 0.0)), z=0.0)
        elif hide_others:
            body = _set(body, "visible", "00")
        return f'<tag type="{kind}"{attrs}>{body}</tag>'

    out = re.sub(TAGBLOCK, fix, xml, flags=re.S)
    missing = set(spec) - seen
    if missing:
        raise KeyError(f"panes not found in donor layout: {sorted(missing)}")
    return out


def identity_materials(xml, names):
    """Reset a material's texture matrix to identity and stop it tiling.

    `BackgroundMaterial` is not an identity material in either donor archive:
    Tantric tiles a half-width texture across a double-width pane, so it ships
    wrap_s=GX_MIRROR on the banner (GX_REPEAT on the icon) *and* XScale=2.0,
    sampling u over 0..2. Dropping a full-bleed image in without resetting both
    renders it at half width and mirrored. Every wrap value has to be matched,
    not just GX_REPEAT -- a rule that only rewrote GX_REPEAT silently missed the
    banner's GX_MIRROR on the previous project.
    """
    def mat(m):
        name, body = m.groups()
        if name in names:
            body = re.sub(r"<wrap_s>\w+</wrap_s>", "<wrap_s>GX_CLAMP</wrap_s>", body)
            body = re.sub(r"<wrap_t>\w+</wrap_t>", "<wrap_t>GX_CLAMP</wrap_t>", body)
            for f, v in (("XTrans", 0.0), ("YTrans", 0.0), ("Rotate", 0.0),
                         ("XScale", 1.0), ("YScale", 1.0)):
                body = re.sub(rf"<{f}>[^<]*</{f}>", f"<{f}>{v:.10f}</{f}>", body)
        return f'<entries name="{name}">{body}</entries>'

    out = re.sub(r'<entries name="([^"]+)">(.*?)</entries>', mat, xml, flags=re.S)
    for n in names:
        if f'<entries name="{n}">' not in out:
            raise KeyError(f"material {n!r} not in donor layout")
    return out


def visible_pictures(xml):
    """[(name, size, translate, alpha, material)] for every visible pic1."""
    out = []
    for m in re.finditer(TAGBLOCK, xml, re.S):
        kind, attrs, body = m.groups()
        if kind != "pic1" or "<visible>01</visible>" not in body:
            continue
        nm = re.search(r'name="([^"]*)"', attrs).group(1)
        sz = re.search(r"<width>([\d.]+)</width>\s*<height>([\d.]+)</height>", body)
        tr = re.search(r"<translate>\s*<x>([-\d.]+)</x>\s*<y>([-\d.]+)</y>", body)
        al = re.search(r"<alpha>(\w+)</alpha>", body)
        mat = re.search(r'<material name="([^"]+)"', body)
        out.append((nm, (float(sz.group(1)), float(sz.group(2))),
                    (float(tr.group(1)), float(tr.group(2))),
                    al.group(1), mat.group(1) if mat else None))
    return out


def pane_translate(xml, name):
    for m in re.finditer(TAGBLOCK, xml, re.S):
        kind, attrs, body = m.groups()
        if kind not in PANE_KINDS:
            continue
        nm = re.search(r'name="([^"]*)"', attrs)
        if nm and nm.group(1) == name:
            tr = re.search(r"<translate>\s*<x>([-\d.]+)</x>\s*<y>([-\d.]+)</y>", body)
            return float(tr.group(1)), float(tr.group(2))
    raise KeyError(name)
