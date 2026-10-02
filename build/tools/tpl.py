"""TPL texture encode/decode for the GX formats this project needs.

GX stores textures in tiles. Tile size depends on the format:
  RGB565 / RGB5A3 : 4x4, 2 bytes per pixel
  RGBA8           : 4x4, stored as two 32-byte halves (AR block, then GB block)
  CI8             : 8x4, 1 byte per pixel
  CI4             : 8x8, 4 bits per pixel
Palette entries are RGB5A3.
"""

import struct

from PIL import Image

MAGIC = 0x0020AF30
I4, I8, IA4, IA8, RGB565, RGB5A3, RGBA8, CI4, CI8, CI14X2, CMPR = \
    0, 1, 2, 3, 4, 5, 6, 8, 9, 10, 14
NAMES = {0: "I4", 1: "I8", 2: "IA4", 3: "IA8", 4: "RGB565", 5: "RGB5A3",
         6: "RGBA8", 8: "CI4", 9: "CI8", 10: "CI14X2", 14: "CMPR"}
TILE = {RGB565: (4, 4), RGB5A3: (4, 4), RGBA8: (4, 4), CI8: (8, 4), CI4: (8, 8),
        I8: (8, 4), I4: (8, 8), IA8: (4, 4), IA4: (8, 4)}


# ------------------------------------------------------------- pixel packing

def _enc_rgb565(r, g, b):
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def _dec_rgb565(v):
    r = (v >> 11) & 0x1F
    g = (v >> 5) & 0x3F
    b = v & 0x1F
    return (r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2), 255


def _enc_rgb5a3(r, g, b, a):
    if a >= 0xE0:                                   # opaque -> 1rrrrrgggggbbbbb
        return 0x8000 | ((r >> 3) << 10) | ((g >> 3) << 5) | (b >> 3)
    return ((a >> 5) << 12) | ((r >> 4) << 8) | ((g >> 4) << 4) | (b >> 4)


def _dec_rgb5a3(v):
    if v & 0x8000:
        r, g, b = (v >> 10) & 0x1F, (v >> 5) & 0x1F, v & 0x1F
        return (r << 3) | (r >> 2), (g << 3) | (g >> 2), (b << 3) | (b >> 2), 255
    a = (v >> 12) & 7
    r, g, b = (v >> 8) & 0xF, (v >> 4) & 0xF, v & 0xF
    return r * 17, g * 17, b * 17, (a << 5) | (a << 2) | (a >> 1)


# -------------------------------------------------------------------- encode

def _tiles(w, h, tw, th):
    for by in range(0, h, th):
        for bx in range(0, w, tw):
            yield bx, by


def encode(img, fmt, palette=None, size=None):
    """Return (texture_bytes, palette_bytes, num_palette_entries).

    For CI4/CI8, `img` is an index map (list of rows) and `size` is required,
    since a plain list has no .size attribute.
    """
    w, h = size if size is not None else img.size
    tw, th = TILE[fmt]
    if fmt in (CI4, CI8):
        assert palette is not None, "palettized formats need a palette"
        idx = img                                    # already an index map (list of lists)
        out = bytearray()
        for bx, by in _tiles(w, h, tw, th):
            if fmt == CI8:
                for y in range(by, by + th):
                    for x in range(bx, bx + tw):
                        out.append(idx[y][x] if y < h and x < w else 0)
            else:
                for y in range(by, by + th):
                    for x in range(bx, bx + tw, 2):
                        hi = idx[y][x] if y < h and x < w else 0
                        lo = idx[y][x + 1] if y < h and x + 1 < w else 0
                        out.append((hi << 4) | lo)
        pal = bytearray()
        for (r, g, b, a) in palette:
            pal += struct.pack(">H", _enc_rgb5a3(r, g, b, a))
        return bytes(out), bytes(pal), len(palette)

    px = img.convert("RGBA").load()
    out = bytearray()
    if fmt == RGBA8:
        for bx, by in _tiles(w, h, tw, th):
            ar, gb = bytearray(), bytearray()
            for y in range(by, by + 4):
                for x in range(bx, bx + 4):
                    r, g, b, a = (px[min(x, w - 1), min(y, h - 1)]
                                  if (x < w and y < h) else (0, 0, 0, 0))
                    ar += bytes((a, r))
                    gb += bytes((g, b))
            out += ar + gb
    else:
        for bx, by in _tiles(w, h, tw, th):
            for y in range(by, by + th):
                for x in range(bx, bx + tw):
                    if x < w and y < h:
                        r, g, b, a = px[x, y]
                    else:
                        r = g = b = a = 0
                    v = _enc_rgb565(r, g, b) if fmt == RGB565 else _enc_rgb5a3(r, g, b, a)
                    out += struct.pack(">H", v)
    return bytes(out), b"", 0


def decode(data, w, h, fmt, pal=None):
    tw, th = TILE[fmt]
    img = Image.new("RGBA", (w, h))
    px = img.load()
    o = 0

    if fmt == RGBA8:
        for bx, by in _tiles(w, h, tw, th):
            blk = data[o:o + 64]
            o += 64
            for i in range(16):
                y, x = by + i // 4, bx + i % 4
                a, r = blk[i * 2], blk[i * 2 + 1]
                g, b = blk[32 + i * 2], blk[32 + i * 2 + 1]
                if x < w and y < h:
                    px[x, y] = (r, g, b, a)
    elif fmt in (RGB565, RGB5A3):
        for bx, by in _tiles(w, h, tw, th):
            for y in range(by, by + th):
                for x in range(bx, bx + tw):
                    v = struct.unpack(">H", data[o:o + 2])[0]
                    o += 2
                    if x < w and y < h:
                        px[x, y] = _dec_rgb565(v) if fmt == RGB565 else _dec_rgb5a3(v)
    elif fmt in (CI4, CI8):
        for bx, by in _tiles(w, h, tw, th):
            for y in range(by, by + th):
                x = bx
                while x < bx + tw:
                    if fmt == CI8:
                        i0 = data[o]
                        o += 1
                        if x < w and y < h:
                            px[x, y] = pal[i0]
                        x += 1
                    else:
                        byte = data[o]
                        o += 1
                        for k, i0 in enumerate((byte >> 4, byte & 0xF)):
                            if x + k < w and y < h:
                                px[x + k, y] = pal[i0]
                        x += 2
    else:
        raise NotImplementedError(NAMES.get(fmt, fmt))
    return img


# ------------------------------------------------------------------ container

def parse(data):
    """Yield dicts describing each texture in a TPL."""
    magic, ntex, hdrsz = struct.unpack(">III", data[:12])
    assert magic == MAGIC, f"bad TPL magic {magic:#x}"
    out = []
    for i in range(ntex):
        toff, poff = struct.unpack(">II", data[12 + i * 8:20 + i * 8])
        h, w, fmt, doff = struct.unpack(">HHII", data[toff:toff + 12])
        pal = None
        npal = 0
        if poff:
            npal, _unp, palfmt, pdoff = struct.unpack(">HHII", data[poff:poff + 12])
            pal = [_dec_rgb5a3(struct.unpack(">H", data[pdoff + j * 2:pdoff + j * 2 + 2])[0])
                   for j in range(npal)]
        out.append(dict(index=i, w=w, h=h, fmt=fmt, data_off=doff, pal=pal,
                        npal=npal, tex_hdr=toff, pal_hdr=poff))
    return out


def build(textures):
    """textures: list of (image_or_indexmap, fmt, palette_or_None, size).

    Layout matches the stock TPLs: header, texture table, texture headers,
    palette headers, then palette data and texture data (32-byte aligned).
    """
    n = len(textures)
    hdr = struct.pack(">III", MAGIC, n, 12)
    table_off = 12
    texhdr_off = table_off + n * 8
    npal_tex = sum(1 for t in textures if t[1] in (CI4, CI8))
    palhdr_off = texhdr_off + n * 0x20
    cur = palhdr_off + npal_tex * 0x0C

    enc = []
    for img, fmt, pal, size in textures:
        e, p, np_ = encode(img, fmt, pal, size)
        enc.append((e, p, np_, fmt, size))

    def align(x, a=32):
        return (x + a - 1) // a * a

    pal_offs, tex_offs = [], []
    for e, p, np_, fmt, size in enc:
        if p:
            cur = align(cur)
            pal_offs.append(cur)
            cur += len(p)
        else:
            pal_offs.append(0)
    for e, p, np_, fmt, size in enc:
        cur = align(cur)
        tex_offs.append(cur)
        cur += len(e)

    out = bytearray(b"\0" * cur)
    out[0:12] = hdr
    pi = 0
    for i, (e, p, np_, fmt, size) in enumerate(enc):
        th = texhdr_off + i * 0x20
        ph = (palhdr_off + pi * 0x0C) if p else 0
        struct.pack_into(">II", out, table_off + i * 8, th, ph)
        w, h = size
        # wrapS/T=0 (clamp), min/mag filter=1 (linear), lodbias 0, unpacked 0
        struct.pack_into(">HHIIIIIIfBBBB", out, th, h, w, fmt, tex_offs[i],
                         0, 0, 1, 1, 0.0, 0, 0, 0, 0)
        if p:
            struct.pack_into(">HHII", out, ph, np_, 0, 2, pal_offs[i])  # palette fmt 2 = RGB5A3
            out[pal_offs[i]:pal_offs[i] + len(p)] = p
            pi += 1
        out[tex_offs[i]:tex_offs[i] + len(e)] = e
    return bytes(out)


def quantize(img, max_colors):
    """Return (indexmap, palette) with one shared palette; None if it doesn't fit."""
    im = img.convert("RGBA")
    w, h = im.size
    px = im.load()
    pal, lut = [], {}
    idx = [[0] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            key = (0, 0, 0, 0) if a == 0 else (r, g, b, a)   # collapse transparent
            if key not in lut:
                if len(pal) >= max_colors:
                    return None
                lut[key] = len(pal)
                pal.append(key)
            idx[y][x] = lut[key]
    return idx, pal
