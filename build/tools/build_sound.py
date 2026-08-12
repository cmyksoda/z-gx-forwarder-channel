"""Build sound.bin: the banner jingle as a non-looping mono BNS.

BNS wraps Nintendo DSP ADPCM (codec 0): 14 samples per 8-byte frame, one
header byte carrying a 4-bit scale exponent and a 4-bit index into 8 pairs of
order-2 predictor coefficients (Q11 fixed point).

Decode, per VGAudio:
    scale     = (1 << (ps & 0xF)) * 2048
    predicted = c1*hist1 + c2*hist2
    sample    = clamp16((predicted + scale*nibble + 1024) >> 11)

The 8 coefficient pairs come from an order-2 LPC fit over each of 8 equal
segments of the file, so they span the material's actual spectral variation.
ffmpeg has no encoder for this format, hence the one below.

Sample rate is the single biggest quality lever, and getting it wrong is what
made the first build sound thin. DSP ADPCM is a *fixed 4 bits per sample* with an
order-2 predictor, so it has no rate/quality trade-off to make: raising the rate
raises the bitrate proportionally AND makes neighbouring samples more predictable,
so the residual shrinks. Measured on this file, against the resampled source:

    rate     overall   0-200 Hz   200-800 Hz   3-8 kHz
    22,050    34.7 dB    34.3       45.5        23.7
    32,000    40.1 dB    41.0       52.4        30.6
    48,000    46.7 dB    49.0       60.7        39.1

Note the low bands: a *higher* rate is what buys bass, which is unintuitive until
you remember the bit budget is per sample, not per second. 22,050 put the noise
floor only ~34 dB down and audibly muddied the bottom end.

**32,000 Hz** is used here because that is what the mGBA GX channel from the
previous project runs at, and it is confirmed good on Jaxi's hardware. 48,000
measures 6.6 dB better again and would still fit the size budget (222 KB against
mGBA GX's 274 KB), but no shipped banner sound is known to use it, so it stays a
documented option rather than the default -- change RATE if you want to try it.

Two things measured and rejected, so they are not silently missing:

* **The coefficient table barely matters.** Fitting eight order-2 predictors to
  the material (what `make_coefs` does) scores 40.1 dB against 39.7 dB for the
  generic table the donor and mGBA GX both ship -- 0.4 dB. The fitted table is
  kept because it is marginally ahead, but this is not where quality lives.
* **A full 16-way scale search gains exactly nothing** over probing the estimate
  +/-1 (40.1 dB either way), so the cheap heuristic in `encode` is already
  optimal and is left alone.

Looping is **off**: audio.wav is plainly a one-shot, opening on silence, building,
and fading to true digital silence with a 1.9 s dead tail. Both the dead tail and
the leading silence are trimmed -- the tail because it costs bytes and plays
nothing, the head because it reads as the channel being slow to respond.
"""

import os
import struct
import subprocess
import sys
import wave

sys.path.insert(0, os.path.dirname(__file__))

from wiilib import imd5_wrap

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BUILD = os.path.join(ROOT, "build")
SRC = os.path.join(ROOT, "audio", "audio.wav")
RATE = 32000                     # matches mGBA GX, which is confirmed good on hardware
LOOP = False                     # audio.wav is a one-shot; see the module docstring
SILENCE = 32                     # |sample| below this counts as silence (of 32768)
HEAD = 0.0                       # seconds of leading silence kept
TAIL = 0.15                      # seconds of silence kept after the last real sample


def read_wav(path):
    with wave.open(path, "rb") as w:
        ch, sw, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    assert sw == 2, f"need 16-bit PCM, got {sw*8}-bit"
    s = list(struct.unpack(f"<{len(raw)//2}h", raw))
    if ch == 2:
        s = [(s[i] + s[i + 1]) // 2 for i in range(0, len(s), 2)]
    return s, rate


def lpc2(x):
    """Optimal order-2 predictor for a block, as Q11 ints."""
    r0 = r1 = r2 = 0
    for i in range(len(x)):
        r0 += x[i] * x[i]
        if i >= 1:
            r1 += x[i] * x[i - 1]
        if i >= 2:
            r2 += x[i] * x[i - 2]
    det = r0 * r0 - r1 * r1
    if r0 == 0 or det == 0:
        return 2048, 0
    a1 = (r1 * r0 - r2 * r1) / det
    a2 = (r0 * r2 - r1 * r1) / det
    q = lambda v: max(-32768, min(32767, int(round(v * 2048))))
    return q(a1), q(a2)


def make_coefs(samples):
    seg = max(1, len(samples) // 8)
    coefs = []
    for i in range(8):
        blk = samples[i * seg:(i + 1) * seg] or samples[-seg:]
        coefs.extend(lpc2(blk))
    return coefs[:16]


def clamp16(v):
    return -32768 if v < -32768 else (32767 if v > 32767 else v)


def encode_frame(targets, c1, c2, h1, h2, e):
    scale = (1 << e) * 2048
    err = 0
    nib = []
    for t in targets:
        pred = c1 * h1 + c2 * h2
        n = int(round(((t << 11) - pred - 1024) / scale))
        n = -8 if n < -8 else (7 if n > 7 else n)
        dec = clamp16((pred + scale * n + 1024) >> 11)
        err += (dec - t) * (dec - t)
        h2, h1 = h1, dec
        nib.append(n)
    return err, nib, h1, h2


def encode(samples, coefs):
    out = bytearray()
    h1 = h2 = 0
    nframes = (len(samples) + 13) // 14
    for f in range(nframes):
        targets = samples[f * 14:f * 14 + 14]
        targets = list(targets) + [0] * (14 - len(targets))
        best = None
        for p in range(8):
            c1, c2 = coefs[p * 2], coefs[p * 2 + 1]
            # estimate the scale from source-history residuals, then probe around it
            maxd, s1, s2 = 0, h1, h2
            for t in targets:
                d = abs((t << 11) - (c1 * s1 + c2 * s2) - 1024)
                maxd = max(maxd, d)
                s2, s1 = s1, t
            e0 = 0
            while e0 < 15 and (1 << e0) * 2048 * 7 < maxd:
                e0 += 1
            for e in {max(0, e0 - 1), e0, min(15, e0 + 1)}:
                err, nib, nh1, nh2 = encode_frame(targets, c1, c2, h1, h2, e)
                if best is None or err < best[0]:
                    best = (err, p, e, nib, nh1, nh2)
        _, p, e, nib, h1, h2 = best
        out.append((p << 4) | e)
        for i in range(0, 14, 2):
            out.append(((nib[i] & 0xF) << 4) | (nib[i + 1] & 0xF))
    return bytes(out)


def decode(data, coefs, count):
    outs = []
    h1 = h2 = 0
    for o in range(0, len(data), 8):
        ps = data[o]
        scale = (1 << (ps & 0xF)) * 2048
        c1, c2 = coefs[((ps >> 4) & 7) * 2], coefs[((ps >> 4) & 7) * 2 + 1]
        for i in range(14):
            b = data[o + 1 + i // 2]
            n = (b >> 4) if i % 2 == 0 else (b & 0xF)
            if n > 7:
                n -= 16
            s = clamp16((c1 * h1 + c2 * h2 + scale * n + 1024) >> 11)
            h2, h1 = h1, s
            outs.append(s)
    return outs[:count]


def build_bns(adpcm, coefs, rate, total, loop=False):
    info = bytearray(96)
    info[0:4] = b"INFO"
    struct.pack_into(">I", info, 4, 96)
    info[8] = 0                       # codec 0 = DSP ADPCM
    info[9] = 1 if loop else 0
    info[10] = 1                      # mono
    struct.pack_into(">H", info, 12, rate)
    struct.pack_into(">I", info, 16, 0)          # loop start
    struct.pack_into(">I", info, 20, total)      # loop end / total samples
    struct.pack_into(">I", info, 24, 0x18)       # -> channel table
    struct.pack_into(">I", info, 32, 0x1C)       # -> channel info
    struct.pack_into(">I", info, 40, 0x28)       # -> coefficients (INFO+0x30)
    for i, c in enumerate(coefs):
        struct.pack_into(">h", info, 48 + i * 2, c)
    data = b"DATA" + struct.pack(">I", len(adpcm) + 8) + adpcm
    head = bytearray(32)
    head[0:4] = b"BNS "
    head[4:8] = bytes.fromhex("feff0100")
    struct.pack_into(">I", head, 8, 32 + len(info) + len(data))
    struct.pack_into(">HH", head, 12, 32, 2)
    struct.pack_into(">II", head, 16, 32, len(info))
    struct.pack_into(">II", head, 24, 32 + len(info), len(data) )
    return bytes(head) + bytes(info) + data


def resample(src, rate):
    """Down-convert to mono 16-bit PCM at `rate` with ffmpeg's soxr."""
    dst = os.path.join(BUILD, "out", "_sound_resampled.wav")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src,
                    "-ac", "1", "-ar", str(rate), "-c:a", "pcm_s16le", dst],
                   check=True, capture_output=True)
    return dst


def trim_tail(samples, rate):
    """Drop trailing digital silence, keeping TAIL seconds of it."""
    last = len(samples) - 1
    while last > 0 and abs(samples[last]) < SILENCE:
        last -= 1
    return samples[:min(len(samples), last + 1 + int(rate * TAIL))]


def trim_head(samples, rate):
    """Drop leading digital silence, keeping HEAD seconds of it.

    audio.wav opens on ~0.45 s of true silence. Keeping it read as the channel
    pausing before responding, so it goes.
    """
    first = 0
    while first < len(samples) and abs(samples[first]) < SILENCE:
        first += 1
    return samples[max(0, first - int(rate * HEAD)):]


def main():
    with wave.open(SRC, "rb") as w:
        print(f"source: {SRC.rsplit('/', 1)[-1]}  {w.getnframes()} frames @ "
              f"{w.getframerate()} Hz, {w.getnchannels()}ch "
              f"({w.getnframes()/w.getframerate():.2f}s)")
    samples, rate = read_wav(resample(SRC, RATE))
    assert rate == RATE, f"ffmpeg gave {rate} Hz, wanted {RATE}"
    before = len(samples)
    samples = trim_head(samples, rate)
    head = before - len(samples)
    samples = trim_tail(samples, rate)
    tail = before - head - len(samples)
    print(f"resampled to {rate} Hz mono; trimmed {head/rate:.2f}s of leading silence "
          f"and {tail/rate:.2f}s of dead tail -> {len(samples)} samples "
          f"({len(samples)/rate:.2f}s)")
    coefs = make_coefs(samples)
    adpcm = encode(samples, coefs)
    back = decode(adpcm, coefs, len(samples))
    num = sum(s * s for s in samples)
    den = sum((a - b) ** 2 for a, b in zip(samples, back)) or 1
    print(f"coefficients: {coefs}")
    print(f"encoded {len(adpcm)} bytes  ratio {len(samples)/len(adpcm):.4f} samples/byte "
          f"(must be 1.75)")
    print(f"round-trip SNR: {10*__import__('math').log10(num/den):.1f} dB")
    bns = build_bns(adpcm, coefs, rate, len(samples), loop=LOOP)
    open(f"{BUILD}/out/sound.bns", "wb").write(bns)
    packed = imd5_wrap(bns)
    open(f"{BUILD}/out/sound.bin", "wb").write(packed)
    print(f"sound.bin: BNS {len(bns):,} bytes -> stored {len(packed):,}  "
          f"(loop flag {'ON' if LOOP else 'OFF'}, donor's is 226,712 bytes)")


if __name__ == "__main__":
    main()
