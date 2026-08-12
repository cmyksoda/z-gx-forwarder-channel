# Z-GX — Wii forwarder channel

Builds `Z-GX - ZGXA [cmyksoda].wad`, a Wii channel that boots `sd:/apps/ZGX/boot.dol`.
The release filename comes from `TITLE`/`TITLE_ID`/`USERNAME` in `build/tools/zgx.py`;
`build.sh` derives it from there rather than hardcoding it.

```
./build/build.sh
```

Rebuilds everything from the assets in the project root, renders previews, and
runs the full verification pass. Needs `wine` (for Benzin), ImageMagick,
`ffmpeg`, and a Python venv with Pillow + pycryptodome + numpy:

```
python3 -m venv build/.venv
build/.venv/bin/pip install Pillow pycryptodome numpy
```

> **`build/build.sh` will not run as-is from a fresh clone.** Two third-party
> inputs are deliberately not redistributed here. Both have fixed homes, so
> nothing needs repointing — create the directories and drop the files in:
>
> - `donor/FCE Ultra GX - FCEU [Tantric].wad`, the channel this one is derived
>   from — get it from the [FCE Ultra GX](https://github.com/dborth/fceugx)
>   channel installer. It stays out because a fakesigned Wii channel carries
>   Nintendo's certificate chain and a ticket, which is a different proposition
>   from shipping GPL'd source or a DOL.
> - `build/tools/benzin/BENZIN.EXE` and its `CYGWIN1.DLL`, which do the
>   `brlyt`/`brlan` XML round-trips. A Windows binary; runs under plain `wine`.
>   Its redistribution terms are unchecked, so it is not vendored either.
>
> Everything else needed is in this repository. Both live *inside* the project
> rather than in a sibling directory, and every tool resolves them from its own
> file location, so nothing breaks when the project is moved — which is exactly
> what happened once, and why they were copied in.

## What goes on the SD card

```
sd:/apps/ZGX/boot.dol      <- Z-GX itself (built from source; see below)
sd:/apps/ZGX/meta.xml      <- Homebrew Channel metadata
sd:/apps/ZGX/icon.png      <- Homebrew Channel icon, 128x48
sd:/ZGX/games/             <- .chd or .cue, subfolders allowed
sd:/ZGX/bios/bios.bin      <- REQUIRED, not included
sd:/ZGX/saves/
sd:/ZGX/art/               <- cover PNGs, 128x192, named exactly as the game
```

The channel passes **no arguments** — it just runs `boot.dol` — so Z-GX finds its
own data under `sd:/ZGX/` exactly as it would when launched from the Homebrew
Channel.

**The BIOS is not optional and cannot ship here** (it is Sega copyright). Upstream
recommends a region-free v1.00 dump at `sd:/ZGX/bios/bios.bin`.

Then install the WAD with your usual WAD manager. It needs a trucha-patched IOS,
same as any fakesigned channel.

### Building Z-GX itself

Upstream (https://github.com/hotker79/Z-GX) ships no prebuilt binary and no
`apps/ZGX` folder, so both `meta.xml` and `icon.png` here were written for this
project rather than taken from upstream — the icon is `logo.png` over a spiral at
128x48, and the metadata is drawn from the README's own credits.

The build needs **libogc2** (Extrems' libogc fork), a matching **libfat**, and
**libchdr**. Upstream's `deps/wii-install-deps-linux.sh` installs those into
`/opt/devkitpro` with `sudo`; this project instead builds them into a shadow
devkitPro prefix so the system install is never touched:

```
B=~/.cache/zgx-build
mkdir -p $B/dkp
for d in devkitPPC tools cmake licenses examples; do ln -s /opt/devkitpro/$d $B/dkp/$d; done
cp -r /opt/devkitpro/portlibs $B/dkp/portlibs
cp /opt/devkitpro/libogc/include/mad.h $B/dkp/portlibs/ppc/include/   # libogc2 needs it

git clone --depth 1 https://github.com/extremscorner/libogc2 $B/libogc2
cd $B/libogc2 && DEVKITPRO=$B/dkp make -j$(nproc) install

git clone --depth 1 https://github.com/extremscorner/libfat $B/libfat
cd $B/libfat && DEVKITPRO=$B/dkp make ogc-release && DEVKITPRO=$B/dkp make -C libogc2 install

git clone --depth 1 https://github.com/rtissera/libchdr $B/libchdr
cd $B/libchdr && powerpc-eabi-cmake CMakeLists.txt -DZSTD_MULTITHREAD_SUPPORT=OFF \
    -DWITH_SYSTEM_ZLIB=ON -DZLIB_LIBRARY=$B/dkp/portlibs/ppc/lib/libz.a \
    -DZLIB_INCLUDE_DIR=$B/dkp/portlibs/ppc/include && make -j$(nproc) chdr-static
cp libchdr-static.a            $B/dkp/portlibs/ppc/lib/libchdr.a
cp deps/lzma-*/libchdr-lzma.a  $B/dkp/portlibs/ppc/lib/liblzma.a
cp deps/zstd-*/libzstd.a       $B/dkp/portlibs/ppc/lib/libzstd.a
cp -r include/libchdr include/dr_libs deps/lzma-*/include/* $B/dkp/portlibs/ppc/include/

git clone --depth 1 https://github.com/hotker79/Z-GX $B/zgx-src
cd $B/zgx-src && DEVKITPRO=$B/dkp make -j$(nproc)        # -> seta-gx.dol
```

Four things are worth knowing, because none are obvious from upstream's script:

- **libfat must be Extrems' fork.** libogc2 ships no libfat, and the stock
  devkitPro one is compiled against plain libogc, so using it would pair a
  libogc2 build with a libogc-built FAT layer.
- **libchdr must be built against zlib, not miniz.** Newer libchdr defaults to
  miniz and then needs `mz_inflate*`, which nothing in Z-GX's `LIBS` provides
  (it links `-lz`). Upstream's script never installs miniz, which is the tell
  that the author's build used zlib. cmake will not find zlib in the cross
  sysroot on its own, hence the explicit `ZLIB_*` paths.
- **libogc2 needs `mad.h`** to compile its mp3 players, and it is not in
  portlibs — only in stock `libogc/include`.
- **libjoy is not needed.** Upstream's script builds and installs it, but nothing
  in `src/` includes it and `LIBS` does not link it.

The final `make` step ends with `cp seta-gx.dol SetaGX/boot.dol`, which fails
because `SetaGX/` is gitignored and exists only on the author's machine. That
error is *after* the DOL is written, so the build is complete; copy `seta-gx.dol`
to `apps/ZGX/boot.dol` yourself.

## Channel properties

```
Title ID      000100015A475841  ("ZGXA")
Boot IOS      58
Contents      3   (banner archive / NAND loader stub / forwarder)
WAD size      1,428,864 bytes
Looks for     sd:/apps/ZGX/boot.dol
```

`ZGXA` is checked against a list of system and known-homebrew channel IDs in
`verify.py`. If you ever want a different one, change `TITLE_ID` in
`build/tools/zgx.py`.

## The animations

Everything about timing lives in `build/tools/zgx.py`, in one block of named
constants. Frames are at 60 fps.

### Icon — 1080-frame (18 s) loop

| | |
|---|---|
| spiral | `BackgroundPicture`, 208×208, Z Rotate 0 → −9 turns **linear** — 180 °/s clockwise |
| logo | `Logo00Picture`, `icon_logo.png` at 80%, pane alpha 0 → 255 → hold → 0 |

2.0 s fade in, **2.0 s held fully visible**, 2.0 s fade out — a 360-frame cycle,
smoothstepped so it eases rather than ramps. The framesize has to be a whole
number of cycles or the fade is cut mid-cycle at the wrap and pops, so 1080 = 3
cycles (the donor's 1200 would give 3.33). The rotation likewise has to be whole
turns: 9 over 1080 frames.

The logo is scaled by resizing the **texture**, not by setting a pane scale, so
the Wii never resamples it and the texture stays 1:1 with its pane.
`ICON_LOGO_SCALE` in zgx.py is the knob. It is cropped to its opaque bbox first,
so the scale applies to the artwork rather than to `icon_logo.png`'s transparent
margins.

### Banner — 1000-frame Start, then a 1000-frame Loop

| frame | |
|---|---|
| 0 → 30 | Saturn console scales 0 → 1 from its centre (0.5 s) |
| 60 | logo starts flying in from off-screen left |
| 120 | logo lands |
| 119 / 126 / 129 | squash to X 0.7 / stretch to Y 1.2, then snap back |
| forever | spiral turns 172.8 °/s clockwise (8 turns per loop) |

**The squish is Tantric's, not invented.** FCE Ultra GX and Snes9x GX ship the
same banner layout, and its `LogoPicture` already does this:

```
X Translation  0:1024   60:-120
X Scale        0:1  59:1  66:0.7  69:1
Y Scale        0:1  59:1  66:1.2  69:1
Y Translation  0:0  125:15  250:0  375:15 ...      (idle float)
```

Those numbers are reproduced verbatim, including the asymmetric 6-frames-in /
3-frames-out recovery that makes it snap, and the fact that the squash begins one
frame *before* the logo stops so it reads as the logo planting itself. Only two
things changed: the travel is mirrored (arrives from the left), and the whole
fly-in is delayed 60 frames so the console finishes opening first.

The donor's idle float on the logo is **disabled** (`BOB_AMPLITUDE = 0`). It was
inherited from the donor's logo animation rather than asked for, and with the
composition raised the logo has only ~17 px of headroom, so a 15 px lift would
crowd the top edge. Raise it if you want the float back.

**The console does not overshoot.** The donor's controller pops to 1.2× before
settling, and this cannot: the console is composed flush with the 4:3 right edge,
so *any* scale above 1.0 clips it on a 4:3 TV for the few frames of the overshoot.
`CONSOLE_OVERSHOOT` is the knob; it needs the console moved left before it can be
raised. `verify.py` checks sprite extents across the whole animation, not just at
rest, so an overshoot that would clip is reported.

**Known warning: the console overhangs the 4:3 area by 5 px.** Since
`saturnmk2.png` was re-exported at 420×238 (from 410×228) it reaches x = 309
against a ±304 limit, so a 4:3 TV shaves 5 px off its right edge. Widescreen is
unaffected. This is the composition as authored, so it is reported as a **warning
rather than a failure** — nudge `PLACEMENT["saturnmk2.png"]` left by 5 to remove
it.

**Rotation direction.** brlyt's +y points up, so a positive Z rotation reads
counter-clockwise and negative is clockwise. Confirmed by rendering the
unmodified donor through `preview.py`: FCE Ultra GX comes out right-side up, its
icon logo above its ground sprites. Clockwise makes the rings appear to travel
*inward* — the classic hypnotic direction. Flip `BANNER_TURNS` / `ICON_TURNS` to
reverse it.

### Spin speed: why one turn per cycle was invisible

The first build rotated once per animation cycle — 21.6 °/s — and read as
completely static on hardware. The reason is geometric, not a broken keyframe:
**an Archimedean spiral is effectively rotation-invariant in appearance.**
Rotating it by θ produces an image identical to shifting its rings radially by
(θ/360) × pitch; at 90° and 180° a re-render with a shifted phase matches the
rotated image *bit for bit* (mean difference 0.00).

So what the eye reads is not degrees per second but **ring creep**, and that is
only one 10 px pitch per whole revolution. At one turn per 16.7 s cycle the rings
crept 0.6 px/s — imperceptible. Measured pixel change over one second:

| rate | pixels visibly different after 1 s |
|---|---|
| 21.6 °/s (original) | 17% |
| 90 °/s | 56% |
| 180 °/s | 92% |

Now ~0.5 revolutions per second, so the rings drift ~5 px/s: clearly moving,
still unhurried. Each figure must stay a whole number of turns, because a full
360° returns the square pane to the orientation it started in and anything else
snaps at the loop wrap.

### Why the rotation keyframes are linear and everything else is not

`<blend>` in a brlan is the **tangent** — value units per frame — not a weight.
Leaving it 0 makes GX interpolate a segment as a smoothstep, which is what gives
Tantric's fades and pops their soft ease. Setting it to the segment's own slope
makes the segment perfectly straight. A constant-speed spin needs the latter or
it visibly stalls at every loop seam; Tantric's own background scroll does the
same thing (`0:0/t0.002 1000:2/t0.002`, and 2/1000 = 0.002).

## The spinning background needs a square, and the square is regenerated

A pane rotates about its own centre, so a pane the size of the viewport sweeps
its corners inside the frame and shows black wedges. The rotating pane has to be
a square whose **inscribed circle** covers the frame:

| | frame | reach from pane centre | pane |
|---|---|---|---|
| banner | 810.67 × 456, lifted 50 | 491.5 | **992 × 992** |
| icon | 170.67 × 96, not lifted | 97.9 | **208 × 208** |

`zgx.spinner_side` derives these rather than hardcoding them, because lifting the
spiral moves its centre away from the bottom corners and so makes the required
square *bigger* — a hardcoded size would silently reintroduce black wedges the
first time the lift changed. `verify.py` re-checks the reach from the pane's
actual centre, not from the origin.

`bg.png` (832×456) and `icon_bg.png` (176×96) cannot be resized into those
squares without distorting the rings, so `build/tools/spiral.py` re-renders the
spiral instead. Its parameters were **fitted to the supplied art**, not chosen:

```
pitch 10.0 px, 50% duty, quarter-pitch phase, centred exactly,
s = (r - pitch*theta/2pi + 2.5) mod pitch          theta = atan2(dy, dx)
```

Fitted independently against `bg.png` and `icon_bg.png`, both landed on the same
pitch and phase and reproduce the source to a **mean per-channel error of
0.20/255** — so the regenerated square is the same spiral, just bigger.
`build.sh` re-checks that every build, and `verify.py` independently confirms the
inscribed circle covers the widescreen frame at all angles.

Because both sources share the 10 px pitch, one generator serves the icon and the
banner at 1:1 texel-to-layout-unit scale.

Handy property: rotating this spiral a full 360° maps the pattern onto itself
(each ring takes its neighbour's place), so a one-turn cycle is seamless.

## Texture formats

| | |
|---|---|
| spiral | **CI4** — 4 bpp, 16-entry palette, stored at 0.75 texel density |
| console, logo | **CI8** — 1 bpp + 512, half of RGB5A3, for 2.5/255 and 1.7/255 error |
| 28 unused donor textures | 4×4 stubs **that keep their names** |

Both sprites are palettised because banner memory is shared system-wide and both
survive it almost free: the console is a grey photo and the logo is black text
with a white outline over one red sphere, so neither has a wide gamut. Alpha
comes along, since TPL palette entries are themselves RGB5A3. Pillow's
`FASTOCTREE` is used because it is the one Pillow quantiser that considers alpha.

The spiral is stored at **0.75 texels per layout unit** (744² for a 992² pane),
with its pitch scaled to match so the rings still land 10 layout units apart on
screen. A rotating square must cover the frame's diagonal, so at 1:1 it stored
2.6× more texels than are ever visible at once — 492 KB, 59% of the whole banner.
At 0.75 the result is indistinguishable at viewing scale (mean difference
5.5/255, ring contrast 99% retained) for 215 KB less. `SPIRAL_TEXEL_SCALE` is the
knob; 0.5 saves 369 KB and is still faithful but visibly softer on the fine outer
rings.

`spiral.render(levels=15)` caps the antialiasing at 16 distinct colours, so a
16-entry palette holds every one of them with **no colours merged**. That is not
bit-exact — TPL palette entries are themselves RGB5A3, so each lands within 5-bit
precision (measured max error 6/255, against 7/255 for RGB565, the format the
previous project's background shipped in). What it buys is size: 960×960 costs
460,800 bytes instead of 1,843,200 as RGBA8, which is the only reason a
full-coverage spinning background fits the memory budget at all.

The stubs keep their names because every entry in the layout's texture list and
every RLTP reference in a brlan must still resolve.

## Sizes

| part | bytes | limit |
|---|---|---|
| `icon.bin` | 39,424 | **102,400 hard cap** (38%) |
| `banner.bin` | 471,168 | 600,000 self-imposed share (79%) |
| `sound.bin` | 136,168 | donor's is 226,712 |

**The icon cap bricks.** `icon.bin` must decompress to at most `0x19000`. That is
a check inside the System Menu, not a budget — over it the buffer is never
allocated and the Menu's LZ77 decompressor writes into address 0, dying right
after the Health & Safety screen.

### Banner memory is a *system-wide* budget, and this got it wrong once

Uncompressed banner memory is shared across **every installed channel**. Exceed
the total and the Wii Menu slows and then hard-freezes while paging the channel
grid with `+`/`-`. Nothing structural detects it.

The first build compared its 839,520-byte banner against FCE Ultra GX's
single 1,388,896-byte banner, called it "57% of budget", and passed — which is
simply the wrong test. Measured across six actually-installed channels:

| channel | banner |
|---|---|
| Snes9x GX | 2,571,296 |
| mGBA GX | 2,571,232 |
| FCE Ultra GX | 1,388,896 |
| Homebrew Channel | 982,560 |
| LSD Dream Emulator | 592,160 |
| **Z-GX** | **471,168** |
| **total** | **8.18 MB** |

So `BANNER_BUDGET` in verify.py is now a strict self-imposed **share** (600,000,
under LSD's 592,160 which shipped fine), and `verify.py` additionally *sums the
banner memory of every channel installed in Dolphin's NAND* and reports it, with
a projection for reinstalling the current WAD. It warns rather than fails,
because the total depends on what happens to be installed rather than on this
WAD — but silence there is how a Menu freeze gets shipped.

Worth stating plainly: two channels account for 5.14 MB of that 8.18 MB. No
amount of shrinking *this* banner fixes a system already over the line.

## Banner sound

**32,000 Hz** mono DSP ADPCM, **loop flag off**, from `audio.wav` (48 kHz stereo,
resampled by ffmpeg). Round-trip SNR 40.0 dB.

### Sample rate is the whole quality story, and 22,050 was wrong

The first build used the donor's 22,050 Hz and sounded thin and bass-light. DSP
ADPCM is a *fixed 4 bits per sample*, so there is no rate/quality trade-off to
make: raising the rate raises the bitrate proportionally **and** makes
neighbouring samples more predictable, shrinking the residual. Measured against
the resampled source:

| rate | overall | 0–200 Hz | 200–800 Hz | 0.8–3 kHz | 3–8 kHz |
|---|---|---|---|---|---|
| 22,050 | 34.7 dB | 34.3 | 45.5 | 36.8 | 23.7 |
| **32,000** | **40.0 dB** | **41.0** | **52.4** | **43.5** | **30.6** |
| 48,000 | 46.7 dB | 49.0 | 60.7 | 52.1 | 39.1 |

Note the low bands — a *higher* rate is what buys bass, which is unintuitive
until you remember the bit budget is per sample, not per second. At 22,050 the
noise floor sat only ~34 dB down and audibly muddied the bottom end.

32,000 is chosen because that is what the mGBA GX channel from the previous
project runs at, and it is confirmed good on hardware. 48,000 measures 6.6 dB
better again and would still fit (222 KB against mGBA GX's 274 KB), but no shipped
banner sound is known to use it, so it stays a documented option — change `RATE`.

Two things measured and **rejected**, so they are not silently missing:

* **The coefficient table barely matters.** Fitting eight order-2 predictors to
  the material scores 40.1 dB against 39.7 dB for the generic table the donor and
  mGBA GX both ship — 0.4 dB. The fitted one is kept for being marginally ahead,
  but quality does not live here.
* **A full 16-way scale search gains exactly nothing** over probing the estimate
  ±1 (40.1 dB either way), so the cheap heuristic in `encode` is already optimal.

Loop is off because `audio.wav` is plainly a one-shot: it opens on silence,
builds, and fades to true digital silence with a 1.9 s dead tail. **Both** the
dead tail and the 0.67 s leading silence are trimmed — the tail because it costs
bytes and plays nothing, the head because it read as the channel being slow to
respond. The trim lands exactly on the attack.

ffmpeg has no encoder for this format, so `build_sound.py` implements one: the
eight predictor pairs are order-2 LPC fits over eight equal segments, quantised
to Q11, and each frame picks the best (predictor, scale) pair.

14 samples per 8-byte frame, with the final frame padded when the sample count
does not divide by 14 — so the invariant is the **frame count**, not a flat 1.75
samples/byte. The previous project asserted exactly 1.75 and only got away with
it because that file's length happened to be a multiple of 14; Tantric's own
banner sound is not (396,506 samples, ratio 1.749991).

## Forwarder

Three in-place edits, and **no code is touched at all** — `verify.py` asserts the
whole `.text` section is byte-identical to Tantric's.

| what | where |
|---|---|
| 4:3 splash PNG | `0x081700`, 165,683 bytes of room |
| 16:9 splash PNG | `0x0A9E40`, 157,270 bytes of room |
| app path string | `0xd3694`, patched **in place** |

**No autoboot patch.** The previous project rewrote the command-line block
because WiiStation only boots a game directly when handed `argc >= 3`. Z-GX is an
ordinary homebrew app that wants no arguments, so Tantric's own one-argument path
is exactly right and is left alone.

**The path string fits in place.** `%s:/apps/fceugx/boot.dol` sits in a 28-byte
hole. `LSD_Dream_Emulator` needed 18 characters and so had to be relocated into
dead space with its `lis`/`addi` pair repointed; `ZGX` is three, so
`%s:/apps/ZGX/boot.dol` is 22 bytes and simply overwrites the old string. No
relocation, no instruction patching. The offset is found by searching for the
original string, not hardcoded.

### Splashes

Must stay **colortype 2** — PNGU rejects palette PNGs outright — and fit the
original byte length.

Stored losslessly, `splash.png` costs 226,383 bytes against a 165,683 budget: the
spiral's ~57 ring pairs are a lot of edges. The fix is to cut the number of
distinct *colours* while still writing RGB, which for two spiral tones plus black
text and a white outline costs almost nothing visually and compresses
enormously. `encode_png` walks a ladder from full colour downwards and stops at
the first setting that fits — 24 colours, 151,993 bytes. Nothing is blurred; this
is synthetic art with crisp edges, and the previous project's
kuwahara/despeckle ladder (built for a noisy photographic scan) would only smear
it.

The **16:9 splash** is authored at 854×480 and pre-squashed to 640×480, so the
TV's stretch cancels the squash. Squashing a rendered spiral with a resampling
filter turns its crisp two-tone rings into gradients — 2,000+ colours and three
times the budget — so the spiral is re-rendered *already elliptical*
(`spiral.render(xscale=)`) and only the "LOADING…" text is resampled onto it. The
text is lifted off its background using the fitted spiral model: against a
re-render, text pixels differ by ≥200 (L1 over RGB) and sit in one block at the
top left, while the scattered 60–200 residue is just antialiasing disagreement.
Taking the ≥200 core, dilating it, and soft-masking only inside that region gives
clean text with no spiral contamination. Result: 119,883 bytes at **full colour**.

The previous project instead squashed to 480 px and filled the side bars by
replicating edge pixels, which on a spiral would streak.

## Layout editing rules

The layouts are **derived from Tantric's donor**, never emitted from scratch. A
hand-built minimal brlyt bricked the System Menu on the previous project (black
screen after Health & Safety) because it omitted the `fnl1` and `grp1` sections,
which the Menu dereferences unconditionally. `verify.py` asserts our section list
matches the donor's exactly.

Pane and material **names are kept as Tantric's**, and only geometry, visibility,
materials and textures change. Names live in a fixed 16-byte field that silently
spills into the following 8-byte `userdata` field, and each is cross-referenced
from the material list, the texture list and both brlans; renaming buys
readability and risks a dangling reference. The mapping instead:

| pane | banner | icon |
|---|---|---|
| `BackgroundPicture` | the spiral | the spiral |
| `ControllerPicture` | the Saturn console | — |
| `LogoPicture` / `Logo00Picture` | the Z-GX logo | the Z-GX logo |

Two traps worth repeating:

- **`BackgroundMaterial` is not an identity material.** It ships `GX_MIRROR`
  (banner) / `GX_REPEAT` (icon) *and* `XScale = 2.0`, because Tantric tiled a
  half-width texture across a double-width pane. Dropping a full-bleed image in
  without resetting wrap **and** the whole texture matrix renders it at half
  width, mirrored. Match *any* wrap value, not just `GX_REPEAT`.
- **`Logo00Pane` ships `alpha = b4` (180)** in the icon, and pane alpha
  multiplies down the tree, so inheriting it would cap the logo at 70% and
  quietly flatten the fade.

The icon's animation is written from scratch rather than patched, because the
donor drives `Logo00Material` with an RLTP texture-swap track cycling
`Logo00.tpl` / `Logo01.tpl`. `Logo01` is a stub here, so keeping that track would
flicker the logo out of existence several times a second. `verify.py` checks that
no RLTP track remains on any material we use.

## Widescreen framing

The Wii always renders a 640×480 anamorphic framebuffer and the System Menu shows
**4/3 more horizontal layout units** in widescreen. Height never changes.

| | 4:3 | 16:9 |
|---|---|---|
| icon | 128 × 96 | 170.67 × 96 |
| banner | 608 × 456 | 810.67 × 456 |

So `verify.py` deliberately does **not** reproduce the previous project's check
that every visible pane is exactly 128×96 / 608×456 — those are 4:3-only truths,
and that assertion actively rejects correct widescreen art (as `Icon_Sizing.md`
warned). It is replaced by a rule admitting both kinds of pane: full-bleed layers
must cover the **widescreen** extent, sprites must sit inside the **4:3** extent,
across the whole animation.

The supplied composition is already 4:3-safe: the logo spans x −297…127 and the
console −108…304 against a ±304 limit.

## Previews

`build/out/` gets, rendered from the **finished** archives rather than from the
build's intentions:

```
icon_preview.gif    banner_start.gif    banner_loop.gif
icon_frames.png     banner_frames.png       (contact sheets, 4:3 area outlined)
```

`preview.py` is a small brlyt/brlan interpreter — it rips the layout and
animations out of the built `icon.bin` / `banner.bin`, decodes the TPLs that are
really in there, and composites with the same cubic-Hermite interpolation GX
uses. If a keyframe is wrong in the WAD it is wrong in the preview too, which is
the point.

The resting banner was checked against `banner.png` directly: the logo and
console land at exactly their authored pixel positions, with a mean residual of
1.85/255 from RGB5A3's 5-bit colour and 3-bit alpha.

`make_readme_previews.py` writes a second, smaller set into `preview/` in the
project root — the four images `README.md` embeds, each asset at both the 4:3 and
the widescreen extent. That set is **committed**, unlike `build/out/`, so it is
regenerated by `build.sh` rather than made by hand; otherwise the screenshots in
the README silently stop matching the channel.

Banners there are stills and icons are GIFs. The icon's whole point is the fade,
while the banner's animation is a one-off intro a still represents fine — and a
100-frame banner GIF came out at **8.8 MB**, because a rotating spiral changes
every pixel every frame and inter-frame compression buys nothing. 64-colour
quantisation keeps the two icon GIFs under 650 KB each, for 1.8 MB total.

## Verification

`build/tools/verify.py` reads the finished WAD back off disk and re-derives
everything from it. It checks content SHA-1s against the TMD, both trucha
signatures, the title ID against a reserved list, that content 1 is still
Tantric's untouched NAND loader stub, IMET MD5 and sizes, U8 parent indices, that
section lists match the donor, that every texture/material/pane a layout or brlan
references exists, 4-pixel texture alignment, the icon cap and banner budget,
material texture matrices, that no RLTP swap survives on a material we use, the
spinner's coverage at all angles, sprite extents across the whole animation, that
every Start track ends on the layout's own resting value, the BNS frame count and
loop flag, and every forwarder patch including that `.text` is untouched.

Run it before installing anything. If a bad WAD ever does take out Dolphin, the
NAND on Linux is at `~/.local/share/dolphin-emu/Wii/` — move
`title/00010001/5a475841` and `ticket/00010001/5a475841.tik` aside and the Menu
boots again.

## Assets

One directory per thing it feeds, matching the LSD project's layout. The paths are
defined once as `ICON_DIR` / `BANNER_DIR` / `SPLASH_DIR` / `AUDIO_DIR` in
`build/tools/zgx.py`, so moving an asset is a one-line change rather than a grep.

| file | used for |
|---|---|
| `banner/bg.png` | reference the spiral generator is fitted and checked against |
| `icon/icon_bg.png` | same, at icon scale |
| `banner/logo.png` | banner logo (421×126) |
| `banner/saturnmk2.png` | banner console (420×238) |
| `icon/icon_logo.png` | icon logo, cropped and scaled to 80% |
| `banner/banner.png` | reference composite — positions are measured from it |
| `splash/splash.png` | both splashes |
| `audio/audio.wav` | banner sound |
| `icon/icon.png`, `banner/banner.xcf`, `icon/icon.xcf`, `banner/Z-GX_copy.jpg` | not used by the build |

Placements were recovered by best-offset search against `banner.png`, matching to
0.002/255 (logo) and 1.6/255 (console) — so they are the authored composition,
not an estimate.

`PLACEMENT` in zgx.py stores where each asset's **opaque bounding-box centre**
goes, not its top-left pixel. That matters: when `saturnmk2.png` was re-exported
from 410×228 to 420×238 with different padding, a top-left placement would have
slid the console sideways, while a bbox-centre placement kept it composed where it
was and just let it change size. `banner.png` is only ever a *reference* — the WAD
is built from the individual assets, so it can go stale without affecting output
(only the composition cross-check).

**The lift is split in two.** `banner.png` already carries the sprites' upward
shift (Jaxi raised the logo 36 px and the console 31.5 px), so `SPRITE_LIFT_Y` is
0 and the sprites simply follow the art. The *spiral* cannot be lifted in
`banner.png` — it is generated — so `SPIRAL_LIFT_Y = 50` raises its centre so it
reads as centred in the area the Menu's title bar leaves. The logo has about 17 px
of headroom left if you want more sprite lift.

`donor/` holds Tantric's FCE Ultra GX WAD and `build/tools/benzin/` holds Benzin,
so the build does not depend on the LSD project's directory still existing.

#### AI Disclosure

The entirety of *this* `.md` file was generated using Claude Code.
