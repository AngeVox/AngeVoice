#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8101}"
VOICE="${VOICE:-zm_010}"
N="${N:-20}"
OUT_DIR="${OUT_DIR:-./loop_outputs}"

mkdir -p "$OUT_DIR"

echo "=== Kokoro TTS Loop Stability Test ==="
echo "BASE_URL=$BASE_URL"
echo "VOICE=$VOICE"
echo "N=$N"
echo "OUT_DIR=$OUT_DIR"
echo

for i in $(seq 1 "$N"); do
  echo "[$i/$N] request..."
  curl -sS -X POST "$BASE_URL/v1/audio/speech" \
    -H "Content-Type: application/json" \
    -d "{\"model\":\"kokoro\",\"input\":\"这是第 ${i} 次循环稳定性测试，用于观察服务是否持续稳定。\",\"voice\":\"$VOICE\",\"response_format\":\"wav\"}" \
    --output "$OUT_DIR/loop_${i}.wav"

  size=$(stat -c%s "$OUT_DIR/loop_${i}.wav")
  if [ "$size" -lt 1000 ]; then
    echo "ERROR: output too small: $OUT_DIR/loop_${i}.wav size=$size"
    exit 1
  fi
done

echo
echo "Final requests:"
curl -sS "$BASE_URL/requests" | python3 -m json.tool

echo
echo "Final stats:"
curl -sS "$BASE_URL/stats" | python3 -m json.tool

echo "=== Loop test finished ==="
