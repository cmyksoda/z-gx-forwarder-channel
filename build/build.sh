#!/usr/bin/env bash
# Rebuild the Z-GX channel WAD from the assets in the project root.
#
#   ./build/build.sh
#
# Needs: a Python venv with Pillow + pycryptodome + numpy, wine (for Benzin),
# ImageMagick, and ffmpeg. Set PY to point at another interpreter if needed.
set -euo pipefail

cd "$(dirname "$0")"
PY="${PY:-$PWD/.venv/bin/python}"

if [ ! -x "$PY" ]; then
  echo "Python venv not found at $PY" >&2
  echo "Create one with:" >&2
  echo "  python3 -m venv build/.venv" >&2
  echo "  build/.venv/bin/pip install Pillow pycryptodome numpy" >&2
  exit 1
fi
for t in wine magick ffmpeg; do
  command -v "$t" >/dev/null || { echo "missing required tool: $t" >&2; exit 1; }
done

mkdir -p out

echo "==> donor (FCE Ultra GX [Tantric])"
"$PY" tools/extract.py

echo "==> spiral generator vs the source art"
"$PY" tools/spiral.py

echo "==> icon.bin"
"$PY" tools/build_icon.py

echo "==> banner.bin"
"$PY" tools/build_banner.py

echo "==> sound.bin"
"$PY" tools/build_sound.py

echo "==> forwarder"
"$PY" tools/patch_forwarder.py

echo "==> WAD"
"$PY" tools/build_wad.py

echo "==> SD staging for Z-GX itself"
"$PY" tools/build_zgx_app.py

echo "==> previews"
"$PY" tools/preview.py

echo "==> README previews (committed, so they must not go stale)"
"$PY" tools/make_readme_previews.py

echo "==> verify"
# derived, not hardcoded, so renaming the release in zgx.py cannot desync this
WAD_NAME="$("$PY" -c 'import sys; sys.path.insert(0, "tools"); import zgx; print(zgx.WAD_NAME)')"
"$PY" tools/verify.py "../$WAD_NAME"

rm -f out/_splash_src_*.png out/_sound_resampled.wav out/_rest_check.png
