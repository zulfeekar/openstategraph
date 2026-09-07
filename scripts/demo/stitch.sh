#!/usr/bin/env bash
# Turn the recorded scenes into one film, plus a poster and a chapter list.
#
# Each scene carries its own playback speed in its file name, because the whole
# point of recording scene by scene is that they do not share one. The name is
# the manifest:
#
#     demo-out/scenes/01-tour@3x.webm        play at 3x
#     demo-out/scenes/05-answer@1x+7.4s.webm play at 1x, join 7.4s in
#
# The `+Ns` part is written by the recorder at the moment it called `cut()`, so
# the seek is measured on the machine that did the recording.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SCENES="$ROOT/demo-out/scenes"
WORK="$ROOT/demo-out/work"
OUT="$ROOT/demo-out"

command -v ffmpeg >/dev/null || { echo "ffmpeg is not installed"; exit 1; }
[ -d "$SCENES" ] || { echo "no scenes in $SCENES — record them first"; exit 1; }

rm -rf "$WORK"; mkdir -p "$WORK"
: > "$WORK/concat.txt"
: > "$OUT/chapters.md"

elapsed=0
found=0

for src in "$SCENES"/*.webm; do
  [ -e "$src" ] || continue
  base="$(basename "$src" .webm)"

  # <order>-<name>@<speed>x[+<trim>s]
  speed="$(printf '%s' "$base" | sed -E 's/.*@([0-9.]+)x.*/\1/')"
  trim="$(printf '%s' "$base" | sed -nE 's/.*\+([0-9.]+)s$/\1/p')"
  name="$(printf '%s' "$base" | sed -E 's/^[0-9]+-//; s/@.*$//')"
  order="$(printf '%s' "$base" | sed -E 's/-.*$//')"
  [ -n "$trim" ] || trim=0

  dst="$WORK/$order.mp4"
  echo "scene $order $name  speed ${speed}x  join ${trim}s"

  # -ss before -i seeks by keyframe and is fast; setpts does the speed change.
  # fps is forced so the concat demuxer never meets two different frame rates.
  ffmpeg -y -loglevel error -ss "$trim" -i "$src" \
    -filter:v "setpts=PTS/$speed,fps=30,scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2" \
    -an -c:v libx264 -preset slow -crf 20 -pix_fmt yuv420p "$dst"

  printf "file '%s'\n" "$dst" >> "$WORK/concat.txt"

  # The chapter mark is where this scene starts in the finished film. Whole
  # seconds: `#t=` takes them, and a chapter list is read by a person.
  whole="$(printf '%.0f' "$elapsed")"
  printf -- "- [%d:%02d](#t=%s) %s\n" \
    "$((whole / 60))" "$((whole % 60))" "$whole" "$name" >> "$OUT/chapters.md"

  dur="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$dst")"
  elapsed="$(echo "$elapsed + $dur" | bc)"
  found=$((found + 1))
done

[ "$found" -gt 0 ] || { echo "no scene files matched"; exit 1; }

ffmpeg -y -loglevel error -f concat -safe 0 -i "$WORK/concat.txt" -c copy "$OUT/demo.mp4"

# A second encoding, because Safari wants h264 and a WebM is smaller elsewhere.
ffmpeg -y -loglevel error -i "$OUT/demo.mp4" \
  -c:v libvpx-vp9 -b:v 0 -crf 34 -row-mt 1 -an "$OUT/demo.webm"

# The poster is the frame the page shows before anyone presses play. One second
# in, so it is never the browser's first blank paint.
ffmpeg -y -loglevel error -ss 1 -i "$OUT/demo.mp4" -frames:v 1 -q:v 3 "$OUT/poster.jpg"

echo
echo "film:   $OUT/demo.mp4  $(du -h "$OUT/demo.mp4" | cut -f1)"
echo "        $OUT/demo.webm $(du -h "$OUT/demo.webm" | cut -f1)"
echo "poster: $OUT/poster.jpg"
echo "length: ${elapsed%.*}s over $found scenes"
echo
cat "$OUT/chapters.md"
