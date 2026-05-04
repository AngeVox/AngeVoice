#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8101}"
VOICE="${VOICE:-zm_010}"
OUT_DIR="${OUT_DIR:-./smoke_outputs}"

mkdir -p "$OUT_DIR"

echo "=== Kokoro TTS Smoke Test ==="
echo "BASE_URL=$BASE_URL"
echo "VOICE=$VOICE"
echo "OUT_DIR=$OUT_DIR"
echo

echo "1) Health check"
curl -sS "$BASE_URL/health" | python3 -m json.tool
echo

echo "2) Initial stats"
curl -sS "$BASE_URL/stats" | python3 -m json.tool
echo

echo "3) OpenAI speech wav test"
time curl -sS -X POST "$BASE_URL/v1/audio/speech" \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"kokoro\",\"input\":\"你好世界，这是服务版冒烟测试。\",\"voice\":\"$VOICE\",\"response_format\":\"wav\"}" \
  --output "$OUT_DIR/openai_1.wav"

ls -lh "$OUT_DIR/openai_1.wav"
file "$OUT_DIR/openai_1.wav" || true
echo

echo "4) Repeat same request to test cache hit"
time curl -sS -X POST "$BASE_URL/v1/audio/speech" \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"kokoro\",\"input\":\"你好世界，这是服务版冒烟测试。\",\"voice\":\"$VOICE\",\"response_format\":\"wav\"}" \
  --output "$OUT_DIR/openai_2_cached.wav"

ls -lh "$OUT_DIR/openai_2_cached.wav"
echo

echo "5) Stats after cache test"
curl -sS "$BASE_URL/stats" | python3 -m json.tool
echo

echo "6) Legacy /api/tts POST test"
time curl -sS -X POST "$BASE_URL/api/tts" \
  -H "Content-Type: application/json" \
  -d "{\"text\":\"这是旧版接口测试。\",\"voice\":\"$VOICE\",\"format\":\"wav\"}" \
  --output "$OUT_DIR/legacy_post.wav"

ls -lh "$OUT_DIR/legacy_post.wav"
echo

echo "7) PCM response test"
time curl -sS -X POST "$BASE_URL/v1/audio/speech" \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"kokoro\",\"input\":\"这是 PCM 格式测试。\",\"voice\":\"$VOICE\",\"response_format\":\"pcm\"}" \
  --output "$OUT_DIR/openai_pcm.raw"

ls -lh "$OUT_DIR/openai_pcm.raw"
echo

echo "8) Invalid format should return 400"
set +e
curl -sS -i -X POST "$BASE_URL/v1/audio/speech" \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"kokoro\",\"input\":\"非法格式测试。\",\"voice\":\"$VOICE\",\"response_format\":\"mp3\"}" \
  | head -n 20
set -e
echo

echo "9) Invalid speed should return 422 or 400"
set +e
curl -sS -i -X POST "$BASE_URL/v1/audio/speech" \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"kokoro\",\"input\":\"非法语速测试。\",\"voice\":\"$VOICE\",\"speed\":3.0,\"response_format\":\"wav\"}" \
  | head -n 20
set -e
echo

echo "10) Long text segmentation test"
LONG_TEXT="第一段测试文本没有问题。第二段测试文本用于观察分段稳定性。第三段测试文本用于观察拼接是否有爆音。第四段测试文本用于测试缓存和队列。第五段测试文本用于检查长文本请求是否能正常完成。"
time curl -sS -X POST "$BASE_URL/v1/audio/speech" \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"kokoro\",\"input\":\"$LONG_TEXT\",\"voice\":\"$VOICE\",\"response_format\":\"wav\"}" \
  --output "$OUT_DIR/long_text.wav"

ls -lh "$OUT_DIR/long_text.wav"
echo

echo "11) Concurrent requests test: 5 parallel requests"
for i in 1 2 3 4 5; do
  (
    time curl -sS -X POST "$BASE_URL/v1/audio/speech" \
      -H "Content-Type: application/json" \
      -d "{\"model\":\"kokoro\",\"input\":\"并发稳定性测试第 ${i} 条。\",\"voice\":\"$VOICE\",\"response_format\":\"wav\"}" \
      --output "$OUT_DIR/concurrent_${i}.wav"
    echo "concurrent_${i}.wav done"
  ) &
done
wait

ls -lh "$OUT_DIR"/concurrent_*.wav
echo

echo "12) Requests status"
curl -sS "$BASE_URL/requests" | python3 -m json.tool
echo

echo "13) Final stats"
curl -sS "$BASE_URL/stats" | python3 -m json.tool
echo

echo "=== Smoke test finished ==="
