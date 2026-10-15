#!/bin/sh
# Une las escenas grabadas por video_demo.js en un único MP4 1280x720 (las del celular, centradas).
#   SALIDA=/tmp/video sh scripts/video_demo.sh virguel_demo.mp4
set -e
SALIDA=${SALIDA:-/tmp/video}
DESTINO=${1:-virguel_demo.mp4}
LISTA="$SALIDA/lista.txt"
: > "$LISTA"
for d in $(ls -d "$SALIDA"/0*/ | sort); do
  webm=$(ls "$d"*.webm | head -1)
  mp4="${d%/}.mp4"
  ffmpeg -loglevel error -y -i "$webm" -vf "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=0x0f172a,fps=25" \
    -c:v libx264 -preset veryfast -crf 26 -pix_fmt yuv420p -an "$mp4"
  echo "file '$mp4'" >> "$LISTA"
done
ffmpeg -loglevel error -y -f concat -safe 0 -i "$LISTA" -c copy "$DESTINO"
echo "Video: $DESTINO"
