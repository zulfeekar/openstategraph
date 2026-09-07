#!/usr/bin/env bash
# Turn the recorded scenes into their films, each with a poster and a chapter
# list.
#
# **Two films, not one.** `demo` is the builder's — the canvas, the run, the
# board. `chat` is the one surface a customer ever sees. Stitched together they
# answer both questions badly: a viewer who wants to know what their customer
# gets would have to sit through forty seconds of node editing to find out. A
# scene declares its film and lands in `demo-out/scenes/<film>/`; every
# directory found there becomes a film, so adding a third is a spec, not an
# edit here.
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

films=0
for film_dir in "$SCENES"/*/; do
  [ -d "$film_dir" ] || continue
  film="$(basename "$film_dir")"
  films=$((films + 1))

  work="$WORK/$film"; mkdir -p "$work"
  : > "$work/concat.txt"
  : > "$OUT/$film-chapters.md"
  elapsed=0
  found=0

  echo "── film: $film"

  for src in "$film_dir"*.webm; do
    [ -e "$src" ] || continue
    base="$(basename "$src" .webm)"

    # <order>-<name>@<speed>x[+<trim>s]
    speed="$(printf '%s' "$base" | sed -E 's/.*@([0-9.]+)x.*/\1/')"
    trim="$(printf '%s' "$base" | sed -nE 's/.*\+([0-9.]+)s$/\1/p')"
    name="$(printf '%s' "$base" | sed -E 's/^[0-9]+-//; s/@.*$//')"
    order="$(printf '%s' "$base" | sed -E 's/-.*$//')"
    [ -n "$trim" ] || trim=0

    dst="$work/$order.mp4"
    echo "   scene $order $name  speed ${speed}x  join ${trim}s"

    # -ss before -i seeks by keyframe and is fast; setpts does the speed change.
    # fps is forced so the concat demuxer never meets two different frame rates.
    ffmpeg -y -loglevel error -ss "$trim" -i "$src" \
      -filter:v "setpts=PTS/$speed,fps=30,scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2" \
      -an -c:v libx264 -preset slow -crf 20 -pix_fmt yuv420p "$dst"

    printf "file '%s'\n" "$dst" >> "$work/concat.txt"

    # The chapter mark is where this scene starts in the finished film. Whole
    # seconds: `#t=` takes them, and a chapter list is read by a person.
    whole="$(printf '%.0f' "$elapsed")"
    printf -- "- [%d:%02d](#t=%s) %s\n" \
      "$((whole / 60))" "$((whole % 60))" "$whole" "$name" >> "$OUT/$film-chapters.md"

    dur="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$dst")"
    elapsed="$(echo "$elapsed + $dur" | bc)"
    found=$((found + 1))
  done

  [ "$found" -gt 0 ] || { echo "   no scenes — skipped"; continue; }

  ffmpeg -y -loglevel error -f concat -safe 0 -i "$work/concat.txt" -c copy "$OUT/$film.mp4"

  # A second encoding, because Safari wants h264 and a WebM is smaller elsewhere.
  ffmpeg -y -loglevel error -i "$OUT/$film.mp4" \
    -c:v libvpx-vp9 -b:v 0 -crf 34 -row-mt 1 -an "$OUT/$film.webm"

  # The poster is the frame the page shows before anyone presses play. One
  # second in, so it is never the browser's first blank paint.
  ffmpeg -y -loglevel error -ss 1 -i "$OUT/$film.mp4" -frames:v 1 -q:v 3 "$OUT/$film-poster.jpg"

  echo "   $OUT/$film.mp4  $(du -h "$OUT/$film.mp4" | cut -f1)   ${elapsed%.*}s over $found scene(s)"
  sed 's/^/     /' "$OUT/$film-chapters.md"
  echo
done

[ "$films" -gt 0 ] || { echo "no film directories under $SCENES"; exit 1; }
