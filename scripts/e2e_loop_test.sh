#!/usr/bin/env bash
# =============================================================================
# AngeVoice 端到端循环测试脚本
# 覆盖：health、voices、HTTP WAV、WebSocket started/audio/done、MOSS、取消恢复、
# 空闲卸载重载、循环压测。
# =============================================================================

set -euo pipefail

BASE_URL="${1:-http://localhost:8101}"
API_KEY="${2:-}"
LOOPS="${3:-30}"
PASS=0
FAIL=0
SKIP=0

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
pass() { echo -e "${GREEN}  ✓ PASS${NC} $1"; PASS=$((PASS + 1)); }
fail() { echo -e "${RED}  ✗ FAIL${NC} $1: $2"; FAIL=$((FAIL + 1)); }
skip() { echo -e "${YELLOW}  ○ SKIP${NC} $1: $2"; SKIP=$((SKIP + 1)); }
section() { echo -e "\n${CYAN}═══ $1 ═══${NC}"; }
require_cmd() { command -v "$1" >/dev/null 2>&1 || { echo "Missing required command: $1" >&2; exit 2; }; }
require_cmd curl; require_cmd jq

AUTH_ARGS=()
[[ -n "$API_KEY" ]] && AUTH_ARGS=(-H "Authorization: Bearer $API_KEY")

curl_json() { curl -s --max-time 30 "${AUTH_ARGS[@]}" "$@"; }

speech_request() {
    local model="$1" text="$2" voice="$3" output="$4"
    curl -s -o "$output" -w '%{http_code}:%{content_type}' --max-time 90 \
        "${BASE_URL}/v1/audio/speech" -H "Content-Type: application/json" "${AUTH_ARGS[@]}" \
        -d "{\"model\":\"${model}\",\"input\":\"${text}\",\"voice\":\"${voice}\"}"
}

check_audio_file() {
    local label="$1" response="$2" file="$3" http_code content_type size
    http_code="${response%%:*}"; content_type="${response#*:}"
    size=$(stat -c%s "$file" 2>/dev/null || echo "0")
    if [[ "$http_code" == "200" && "$size" -gt 1000 && "$content_type" == audio/* ]]; then
        pass "$label ($size bytes, $content_type)"; return 0
    fi
    fail "$label" "HTTP=$http_code content-type=$content_type size=$size body=$(head -c 200 "$file" 2>/dev/null || true)"; return 1
}

section "1. Health Check"
HTTP_CODE=$(curl -s -o /tmp/av_health.json -w '%{http_code}' "${AUTH_ARGS[@]}" "${BASE_URL}/health" --max-time 10)
if [[ "$HTTP_CODE" == "200" ]]; then
    STATUS=$(jq -r '.status // "unknown"' /tmp/av_health.json 2>/dev/null || echo "parse_error")
    HEALTHY=$(jq -r '.healthy // true' /tmp/av_health.json 2>/dev/null || echo "true")
    MODEL=$(jq -r '.current_model // "unknown"' /tmp/av_health.json 2>/dev/null || echo "unknown")
    if [[ "$STATUS" == "ok" && "$HEALTHY" == "true" ]]; then
        pass "Health OK (model=$MODEL)"
    elif [[ "$STATUS" == "loading" ]]; then
        pass "Health endpoint reachable but model is still loading"
    else
        fail "Health degraded" "status=$STATUS unhealthy=$(jq -c '.unhealthy_models // []' /tmp/av_health.json 2>/dev/null || echo "[]")"
    fi
else
    fail "Health check" "HTTP $HTTP_CODE"
fi

section "2. Voices List"
BODY=$(curl_json "${BASE_URL}/v1/audio/voices")
VOICE_COUNT=$(echo "$BODY" | jq '.voices | length' 2>/dev/null || echo "0")
[[ "$VOICE_COUNT" -gt 0 ]] && pass "Voices listed ($VOICE_COUNT voices)" || fail "Voices list" "0 voices returned: $(echo "$BODY" | head -c 200)"

section "3. Kokoro WAV Synthesis"
KOKORO_WAV="/tmp/av_e2e_kokoro.wav"
check_audio_file "Kokoro WAV" "$(speech_request "kokoro" "测试合成，这是一段中文语音。" "af_xiaobei" "$KOKORO_WAV")" "$KOKORO_WAV" || true

section "4. Kokoro WebSocket Stream"
if command -v websocat >/dev/null 2>&1; then
    WS_URL="${BASE_URL/#http/ws}/ws/v1/tts"
    WS_PAYLOAD='{ "model":"kokoro", "text":"WebSocket流式测试，需要真实音频和完成帧。", "voice":"af_xiaobei", "format":"pcm_s16le" }'
    [[ -n "$API_KEY" ]] && WS_PAYLOAD="{ \"model\":\"kokoro\", \"text\":\"WebSocket流式测试，需要真实音频和完成帧。\", \"voice\":\"af_xiaobei\", \"format\":\"pcm_s16le\", \"token\":\"${API_KEY}\" }"
    WS_RESULT=$(printf '%s\n' "$WS_PAYLOAD" | timeout 45 websocat "$WS_URL" 2>/tmp/av_ws_err || echo "ws_error")
    WS_STARTED=$(printf '%s\n' "$WS_RESULT" | jq -s 'map(select(.type == "started")) | length' 2>/dev/null || echo 0)
    WS_AUDIO=$(printf '%s\n' "$WS_RESULT" | jq -s 'map(select(.type == "audio" and ((.data // "") | length) > 100)) | length' 2>/dev/null || echo 0)
    WS_DONE=$(printf '%s\n' "$WS_RESULT" | jq -s 'map(select(.type == "done")) | length' 2>/dev/null || echo 0)
    if [[ "$WS_RESULT" != *"ws_error"* && "$WS_STARTED" -gt 0 && "$WS_AUDIO" -gt 0 && "$WS_DONE" -gt 0 ]]; then
        pass "WebSocket returned started + audio + done (audio_chunks=$WS_AUDIO)"
    else
        fail "WebSocket stream" "started=$WS_STARTED audio=$WS_AUDIO done=$WS_DONE response=$(echo "$WS_RESULT" | head -c 300) stderr=$(cat /tmp/av_ws_err 2>/dev/null | head -c 200)"
    fi
else
    skip "WebSocket stream" "websocat not installed"
fi

section "5. Optional MOSS CPU HTTP Audio"
MODELS_JSON=$(curl_json "${BASE_URL}/v1/models")
if echo "$MODELS_JSON" | jq -e '.models[]? | select(.id == "moss-nano-cpu" and .available == true)' >/dev/null 2>&1; then
    MOSS_WAV="/tmp/av_e2e_moss_cpu.wav"
    check_audio_file "MOSS CPU audio" "$(speech_request "moss-nano-cpu" "MOSS CPU合成测试。" "Junhao" "$MOSS_WAV")" "$MOSS_WAV" || true
else
    skip "MOSS CPU audio" "moss-nano-cpu is not enabled/available"
fi

section "6. Optional MOSS CUDA HTTP Audio"
if echo "$MODELS_JSON" | jq -e '.models[]? | select(.id == "moss-nano-cuda" and .available == true)' >/dev/null 2>&1; then
    CUDA_WAV="/tmp/av_e2e_moss_cuda.wav"
    check_audio_file "MOSS CUDA audio" "$(speech_request "moss-nano-cuda" "MOSS CUDA合成测试。" "Junhao" "$CUDA_WAV")" "$CUDA_WAV" || true
else
    skip "MOSS CUDA audio" "moss-nano-cuda is not enabled/available"
fi

section "7. Cancel / Abort Recovery"
timeout 2 curl -s -o /tmp/av_e2e_cancel.wav --max-time 10 "${BASE_URL}/v1/audio/speech" -H "Content-Type: application/json" "${AUTH_ARGS[@]}" -d '{"model":"kokoro","input":"这段文字很长需要大量计算，我们会在中途取消它以测试取消功能是否正常工作。让我们继续添加更多文字来确保合成时间足够长以便能够成功取消。再来一些中文内容填充。","voice":"af_xiaobei","speed":0.3}' >/dev/null 2>&1 || true
sleep 1
HEALTH_AFTER=$(curl -s -w '%{http_code}' -o /dev/null "${AUTH_ARGS[@]}" "${BASE_URL}/health" --max-time 5)
[[ "$HEALTH_AFTER" == "200" ]] && pass "Cancel/abort did not break health endpoint" || fail "Cancel recovery" "Health after cancel: HTTP $HEALTH_AFTER"

section "8. Optional Idle Unload + Reload"
IDLE_TIMEOUT=$(jq -r '.model.idle_timeout_seconds // .model.model_idle_timeout_seconds // .model_idle_timeout_seconds // 0' /tmp/av_health.json 2>/dev/null || echo "0")
CHECK_INTERVAL=$(jq -r '.model.idle_check_interval // .model.model_idle_check_interval // .model_idle_check_interval // 30' /tmp/av_health.json 2>/dev/null || echo "30")
if [[ "$IDLE_TIMEOUT" =~ ^[0-9]+(\.[0-9]+)?$ ]] && awk "BEGIN {exit !($IDLE_TIMEOUT > 0 && $IDLE_TIMEOUT <= 60)}"; then
    WAIT_TIME=$(awk "BEGIN {printf \"%.0f\", $IDLE_TIMEOUT + $CHECK_INTERVAL + 5}")
    echo "  Idle timeout is ${IDLE_TIMEOUT}s; waiting ${WAIT_TIME}s for an unload cycle..."
    sleep "$WAIT_TIME"
    AFTER_IDLE=$(curl_json "${BASE_URL}/v1/models")
    LOADED_AFTER_IDLE=$(echo "$AFTER_IDLE" | jq '[.models[]? | select(.loaded == true)] | length' 2>/dev/null || echo 999)
    [[ "$LOADED_AFTER_IDLE" -eq 0 ]] && pass "Idle unload released all loaded models" || fail "Idle unload" "loaded models after idle=$LOADED_AFTER_IDLE payload=$(echo "$AFTER_IDLE" | head -c 300)"
    RELOAD_WAV="/tmp/av_e2e_reload.wav"
    check_audio_file "Idle unload + auto reload" "$(speech_request "kokoro" "重载测试。" "af_xiaobei" "$RELOAD_WAV")" "$RELOAD_WAV" || true
else
    skip "Idle unload + reload" "timeout disabled or too long for e2e; set ANGEVOICE_IDLE_TIMEOUT_SECONDS<=60 in test env"
fi

section "9. Loop Stress Test ($LOOPS iterations)"
STRESS_PASS=0; STRESS_FAIL=0
for i in $(seq 1 "$LOOPS"); do
    OUT="/tmp/av_e2e_stress_${i}.wav"
    RESP=$(speech_request "kokoro" "压测第${i}轮测试语音合成稳定性。" "af_xiaobei" "$OUT")
    CODE="${RESP%%:*}"; SIZE=$(stat -c%s "$OUT" 2>/dev/null || echo "0")
    if [[ "$CODE" == "200" && "$SIZE" -gt 1000 ]]; then
        STRESS_PASS=$((STRESS_PASS + 1))
    else
        STRESS_FAIL=$((STRESS_FAIL + 1)); echo -e "  ${RED}✗ Iteration $i failed (HTTP $CODE size=$SIZE)${NC}"
    fi
    (( i % 10 == 0 )) && echo -e "  ${CYAN}Progress: $i/$LOOPS (pass=$STRESS_PASS fail=$STRESS_FAIL)${NC}"
done

[[ "$STRESS_FAIL" -eq 0 ]] && pass "Stress test: $STRESS_PASS/$LOOPS all passed" || fail "Stress test" "$STRESS_FAIL/$LOOPS failed"

echo ""; echo -e "${CYAN}══════════════════════════════════════════════════${NC}"
echo -e "  ${GREEN}PASS: $PASS${NC}  ${RED}FAIL: $FAIL${NC}  ${YELLOW}SKIP: $SKIP${NC}"
echo -e "${CYAN}══════════════════════════════════════════════════${NC}"
[[ "$FAIL" -gt 0 ]] && { echo -e "\n${RED}Some tests failed!${NC}"; exit 1; }
echo -e "\n${GREEN}All required tests passed!${NC}"
exit 0
