"""Minimal Wii WAD / U8 / LZ77 / IMD5 / IMET toolkit.

Written for this project because libWiiSharp is x86-Windows-only and has two
documented data-corruption bugs (U8.FromDirectory writes garbage directory
parent indices; Lz77.Decompress silently zero-fills). Everything here is
verified by byte-exact round-trip against Tantric's stock FCE Ultra GX WAD.
"""

import hashlib
import struct

from Crypto.Cipher import AES

COMMON_KEY = bytes.fromhex("ebe42a225e8593e448d9c5457381aaf7")

ALIGN = lambda n, a=64: (n + a - 1) // a * a


def _pad(b, a=64):
    return b + b"\0" * (ALIGN(len(b), a) - len(b))


# ---------------------------------------------------------------- LZ77 (0x10)

def lz77_decompress(data):
    """Type-0x10 LZ77. `data` starts at the 0x10 header (magic already stripped)."""
    assert data[0] == 0x10, "not a type-0x10 stream"
    out_size = int.from_bytes(data[1:4], "little")
    out = bytearray()
    pos = 4
    while len(out) < out_size:
        flags = data[pos]
        pos += 1
        for bit in range(8):
            if len(out) >= out_size:
                break
            if flags & (0x80 >> bit):
                b0, b1 = data[pos], data[pos + 1]
                pos += 2
                length = (b0 >> 4) + 3
                disp = ((b0 & 0x0F) << 8 | b1) + 1
                start = len(out) - disp
                for i in range(length):
                    out.append(out[start + i])
            else:
                out.append(data[pos])
                pos += 1
    return bytes(out)


def lz77_compress(src):
    """Greedy encoder with a 3-byte-prefix hash chain (window 4096, match 3..18)."""
    n = len(src)
    out = bytearray(b"\x10" + n.to_bytes(3, "little"))
    heads, prevs = {}, [-1] * n
    pos = 0
    flag_pos = None
    flag_bit = 0
    while pos < n:
        if flag_bit == 0:
            flag_pos = len(out)
            out.append(0)
        best_len, best_disp = 0, 0
        if pos + 3 <= n:
            key = src[pos:pos + 3]
            cand = heads.get(key, -1)
            limit = max(0, pos - 4096)
            tries = 0
            while cand >= limit and tries < 256:
                mlen = 0
                maxlen = min(18, n - pos)
                while mlen < maxlen and src[cand + mlen] == src[pos + mlen]:
                    mlen += 1
                if mlen > best_len:
                    best_len, best_disp = mlen, pos - cand
                    if mlen == 18:
                        break
                cand = prevs[cand]
                tries += 1
        if best_len >= 3:
            out[flag_pos] |= 0x80 >> flag_bit
            out.append(((best_len - 3) << 4) | ((best_disp - 1) >> 8))
            out.append((best_disp - 1) & 0xFF)
            adv = best_len
        else:
            out.append(src[pos])
            adv = 1
        for i in range(pos, min(pos + adv, n - 2)):
            key = src[i:i + 3]
            prevs[i] = heads.get(key, -1)
            heads[key] = i
        pos += adv
        flag_bit = (flag_bit + 1) & 7
    return bytes(out)


# ----------------------------------------------------------------- IMD5 / U8

def imd5_wrap(payload):
    """32-byte IMD5 header. Length and MD5 cover everything after the header."""
    return (b"IMD5" + struct.pack(">I", len(payload)) + b"\0" * 8
            + hashlib.md5(payload).digest() + payload)


def imd5_unwrap(data):
    assert data[:4] == b"IMD5", "missing IMD5"
    size = struct.unpack(">I", data[4:8])[0]
    body = data[32:32 + size]
    assert hashlib.md5(body).digest() == data[16:32], "IMD5 md5 mismatch"
    return body


def pack_lz77_imd5(u8_bytes):
    """banner.bin / icon.bin layout: IMD5 | 'LZ77' magic | 0x10 stream."""
    return imd5_wrap(b"LZ77" + lz77_compress(u8_bytes))


def unpack_lz77_imd5(data):
    body = imd5_unwrap(data)
    if body[:4] == b"LZ77":
        return lz77_decompress(body[4:])
    return body


class U8Node:
    __slots__ = ("is_dir", "name", "data", "parent", "last")

    def __init__(self, is_dir, name, data=b"", parent=0, last=0):
        self.is_dir, self.name, self.data = is_dir, name, data
        self.parent, self.last = parent, last


class U8:
    """U8 archive. Parses into a flat node list and rebuilds preserving the
    exact tree layout -- never regenerate parent indices from scratch."""

    MAGIC = 0x55AA382D

    def __init__(self, nodes):
        self.nodes = nodes

    @classmethod
    def load(cls, data):
        magic, root_off, header_size, data_off = struct.unpack(">IIII", data[:16])
        assert magic == cls.MAGIC, "Invalid U8 magic"
        base = root_off
        _, _, root_last = cls._read_node(data, base)
        count = root_last
        string_base = base + count * 12
        nodes = []
        for i in range(count):
            typ, name_off, off, size = cls._read_raw(data, base + i * 12)
            end = data.index(b"\0", string_base + name_off)
            name = data[string_base + name_off:end].decode("ascii")
            if typ:
                nodes.append(U8Node(True, name, b"", off, size))
            else:
                nodes.append(U8Node(False, name, data[off:off + size]))
        return cls(nodes)

    @staticmethod
    def _read_raw(data, o):
        typ = data[o]
        name_off = int.from_bytes(data[o + 1:o + 4], "big")
        off, size = struct.unpack(">II", data[o + 4:o + 12])
        return typ, name_off, off, size

    @classmethod
    def _read_node(cls, data, o):
        return cls._read_raw(data, o)[0], cls._read_raw(data, o)[2], cls._read_raw(data, o)[3]

    def paths(self):
        """Yield (index, full_path) for every node."""
        stack = []
        for i, nd in enumerate(self.nodes):
            while stack and stack[-1][1] <= i:
                stack.pop()
            prefix = "/".join(s[0] for s in stack)
            path = (prefix + "/" + nd.name) if prefix else nd.name
            yield i, path
            if nd.is_dir:
                stack.append((nd.name, nd.last))

    def find(self, path):
        for i, p in self.paths():
            if p == path or p == "/" + path:
                return i
        raise KeyError(path)

    def replace(self, path, data):
        self.nodes[self.find(path)].data = data

    def get(self, path):
        return self.nodes[self.find(path)].data

    def rename(self, path, new_name):
        self.nodes[self.find(path)].name = new_name

    def to_bytes(self):
        count = len(self.nodes)
        # string table
        strings = bytearray()
        offs = []
        for nd in self.nodes:
            offs.append(len(strings))
            strings += nd.name.encode("ascii") + b"\0"
        header_size = count * 12 + len(strings)
        data_off = ALIGN(0x20 + header_size, 64)
        # file data, 32-byte aligned as the originals are
        blobs, cur = [], data_off
        for nd in self.nodes:
            if nd.is_dir:
                blobs.append(None)
                continue
            cur = ALIGN(cur, 32)
            blobs.append(cur)
            cur += len(nd.data)
        total = ALIGN(cur, 32)
        out = bytearray(b"\0" * total)
        out[0:16] = struct.pack(">IIII", self.MAGIC, 0x20, header_size, data_off)
        for i, nd in enumerate(self.nodes):
            o = 0x20 + i * 12
            if nd.is_dir:
                out[o] = 1
                out[o + 1:o + 4] = offs[i].to_bytes(3, "big")
                out[o + 4:o + 12] = struct.pack(">II", nd.parent, nd.last)
            else:
                out[o] = 0
                out[o + 1:o + 4] = offs[i].to_bytes(3, "big")
                out[o + 4:o + 12] = struct.pack(">II", blobs[i], len(nd.data))
                out[blobs[i]:blobs[i] + len(nd.data)] = nd.data
        out[0x20 + count * 12:0x20 + count * 12 + len(strings)] = strings
        return bytes(out)

    def check_tree(self):
        """The check that catches the FromDirectory brick: every directory's
        parent index must point at a real enclosing directory."""
        problems = []
        for i, path in self.paths():
            nd = self.nodes[i]
            if not nd.is_dir:
                continue
            depth = path.count("/")
            expect = 0 if depth == 0 else None
            if nd.parent >= len(self.nodes) or not self.nodes[nd.parent].is_dir:
                problems.append(f"{path}: parent {nd.parent} invalid")
            elif expect == 0 and nd.parent != 0:
                problems.append(f"{path}: parent {nd.parent} != 0")
            if nd.last > len(self.nodes):
                problems.append(f"{path}: last {nd.last} out of range")
        return problems


# --------------------------------------------------------------------- IMET

# IMET, relative to the "IMET" magic (verified against Tantric's FCEUGX WAD):
#   +0x00 magic, +0x04 hashSize(0x600), +0x08 unk(3),
#   +0x0C icon/banner/sound sizes, +0x18 flag,
#   +0x1C names[10][42] UTF-16BE  <- ten language slots, not eight
#   +0x5B0 md5
# The MD5 covers [magic-0x40, magic-0x40+0x600) with the md5 field zeroed.
# The three sizes are the *uncompressed* payload sizes after the IMD5 header.
IMET_NAMES = 0x1C
IMET_MD5 = 0x5B0
IMET_LANGS = 10


def imet_titles(banner_app_bytes):
    """Read the 8 language titles out of an IMET header (UTF-16BE, 42 chars)."""
    off = banner_app_bytes.find(b"IMET")
    names = []
    base = off + IMET_NAMES
    for i in range(IMET_LANGS):
        raw = banner_app_bytes[base + i * 84:base + i * 84 + 84]
        names.append(raw.decode("utf-16-be").split("\0")[0])
    return off, names


def imet_set(data, title, sizes=None):
    """Set all 8 language slots and refresh the IMET MD5.

    IMET stores the *uncompressed* sizes of icon/banner/sound, so they must be
    updated whenever those archives change.
    """
    data = bytearray(data)
    off = data.find(b"IMET")
    assert off >= 0, "no IMET"
    if sizes:
        icon_sz, banner_sz, sound_sz = sizes
        struct.pack_into(">III", data, off + 0x0C, icon_sz, banner_sz, sound_sz)
    enc = title.encode("utf-16-be")[:82]
    enc += b"\0" * (84 - len(enc))
    for i in range(IMET_LANGS):
        data[off + IMET_NAMES + i * 84:off + IMET_NAMES + i * 84 + 84] = enc
    hash_off = off + IMET_MD5
    start = off - 0x40
    tmp = bytearray(data)
    tmp[hash_off:hash_off + 16] = b"\0" * 16
    digest = hashlib.md5(bytes(tmp[start:start + 0x600])).digest()
    data[hash_off:hash_off + 16] = digest
    return bytes(data)


def imet_verify(data):
    off = data.find(b"IMET")
    start = off - 0x40
    tmp = bytearray(data)
    tmp[off + IMET_MD5:off + IMET_MD5 + 16] = b"\0" * 16
    return hashlib.md5(bytes(tmp[start:start + 0x600])).digest() == \
        data[off + IMET_MD5:off + IMET_MD5 + 16]


# ---------------------------------------------------------------------- WAD

class WAD:
    def __init__(self, certs, crl, tik, tmd, contents, footer):
        self.certs, self.crl, self.tik, self.tmd = certs, crl, tik, tmd
        self.contents = contents          # list of *decrypted* content bytes
        self.footer = footer

    # -- ticket/tmd helpers
    @property
    def title_id(self):
        return self.tmd[0x18C:0x194]

    def title_key(self):
        iv = self.tik[0x1DC:0x1E4] + b"\0" * 8
        enc = self.tik[0x1BF:0x1CF]
        return AES.new(COMMON_KEY, AES.MODE_CBC, iv).decrypt(enc)

    @classmethod
    def load(cls, path):
        d = open(path, "rb").read()
        hdr, wtype, cert_sz, crl_sz, tik_sz, tmd_sz, data_sz, foot_sz = \
            struct.unpack(">IIIIIIII", d[:32])
        o = ALIGN(hdr)
        def take(n):
            nonlocal o
            b = d[o:o + n]
            o = ALIGN(o + n)
            return b
        certs, crl, tik, tmd = take(cert_sz), take(crl_sz), take(tik_sz), take(tmd_sz)
        self = cls(certs, crl, tik, tmd, [], b"")
        key = self.title_key()
        n = struct.unpack(">H", tmd[0x1DE:0x1E0])[0]
        contents = []
        for i in range(n):
            e = 0x1E4 + i * 36
            idx = struct.unpack(">H", tmd[e + 4:e + 6])[0]
            size = struct.unpack(">Q", tmd[e + 8:e + 16])[0]
            blob = d[o:o + ALIGN(size, 16)]
            o = ALIGN(o + ALIGN(size, 16))
            iv = struct.pack(">H", idx) + b"\0" * 14
            contents.append(AES.new(key, AES.MODE_CBC, iv).decrypt(blob)[:size])
        self.contents = contents
        self.footer = d[o:o + foot_sz]
        return self

    def set_title_id(self, tid4):
        """tid4 is the 4-char ASCII channel code, e.g. 'LSDE'."""
        assert len(tid4) == 4
        new = self.title_id[:4] + tid4.encode("ascii")
        self.tmd = self.tmd[:0x18C] + new + self.tmd[0x194:]
        # ticket must match, and the title key is IV'd by the title ID, so
        # re-encrypt the key under the new ID to keep it decrypting to the same value
        key = self.title_key()
        self.tik = self.tik[:0x1DC] + new + self.tik[0x1E4:]
        iv = new + b"\0" * 8
        enc = AES.new(COMMON_KEY, AES.MODE_CBC, iv).encrypt(key)
        self.tik = self.tik[:0x1BF] + enc + self.tik[0x1CF:]

    def _refresh_tmd(self):
        tmd = bytearray(self.tmd)
        for i, c in enumerate(self.contents):
            e = 0x1E4 + i * 36
            struct.pack_into(">Q", tmd, e + 8, len(c))
            tmd[e + 16:e + 36] = hashlib.sha1(c).digest()
        self.tmd = bytes(tmd)

    @staticmethod
    def _fakesign(blob, brute_off):
        """Zero the RSA signature, then brute-force two padding bytes until the
        SHA-1 of the signed region starts with 0x00 (the 'trucha' condition)."""
        b = bytearray(blob)
        b[4:4 + 256] = b"\0" * 256
        for v in range(0x10000):
            struct.pack_into(">H", b, brute_off, v)
            if hashlib.sha1(bytes(b[0x140:])).digest()[0] == 0:
                return bytes(b)
        raise RuntimeError("fakesign failed")

    def save(self, path, fakesign=True):
        self._refresh_tmd()
        if fakesign:
            self.tmd = self._fakesign(self.tmd, 0x19A)   # TMD  padding after groupID
            self.tik = self._fakesign(self.tik, 0x262)   # ticket padding
        key = self.title_key()
        blobs = []
        for i, c in enumerate(self.contents):
            e = 0x1E4 + i * 36
            idx = struct.unpack(">H", self.tmd[e + 4:e + 6])[0]
            iv = struct.pack(">H", idx) + b"\0" * 14
            padded = c + b"\0" * (ALIGN(len(c), 16) - len(c))
            blobs.append(AES.new(key, AES.MODE_CBC, iv).encrypt(padded))
        data_sz = sum(ALIGN(len(b)) for b in blobs[:-1]) + len(blobs[-1]) if blobs else 0
        head = struct.pack(">IIIIIIII", 0x20, 0x49730000, len(self.certs),
                           len(self.crl), len(self.tik), len(self.tmd),
                           data_sz, len(self.footer))
        out = bytearray(_pad(head))
        for part in (self.certs, self.crl, self.tik, self.tmd):
            out += _pad(part)
        for b in blobs:
            out += _pad(b)
        if self.footer:
            out += _pad(self.footer)
        open(path, "wb").write(bytes(out))
        return len(out)
