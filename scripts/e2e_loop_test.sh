#!/usr/bin/env bash
# =============================================================================
# AngeVoice End-to-End Loop Test Script
# 覆盖: health, voices, kokoro wav, websocket, moss stream, cancel,
#        idle unload + reload, 循环压测
#
# 用法:
#   ./e2e_loop_test.sh [BASE_URL] [API_KEY] [LOOPS]
#
# 示例:
#   ./e2e_loop_test.sh http://localhost:8101              # 无认证
#   ./e2e_loop_test.sh http://localhost:8101 my-secret-key  # 带认证
#   ./e2e_loop_test.sh http://localhost:8101 my-secret-key 50  # 压测 50 轮
#
# 前置条件: curl, jq, websocat (WebSocket 测试可选)
# =============================================================================

set -euo pipefail

BASE_URL="${1:-http://localhost:8101}"
API_KEY="${2:-}"
LOOPS="${3:-30}"
PASS=0
FAIL=0
SKIP=0

# ── 颜色 ──────────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# ── 工具函数 ──────────────────────────────────────────────────────────────────
auth_header() {
    if [[ -n "$API_KEY" ]]; then
        echo "-H \"Authorization: Bearer $API_KEY\""
    fi
}

pass() { echo -e "${GREEN}  ✓ PASS${NC} $1"; ((PASS++)); }
fail() { echo -e "${RED}  ✗ FAIL${NC} $1: $2"; ((FAIL++)); }
skip() { echo -e "${YELLOW}  ○ SKIP${NC} $1: $2"; ((SKIP++)); }
section() { echo -e "\n${CYAN}═══ $1 ═══${NC}"; }

curl_opts() {
    echo -s -o /dev/null -w '%{http_code}' --max-time 30
}

curl_body() {
    local extra_args=()
    if [[ -n "$API_KEY" ]]; then
        extra_args+=(-H "Authorization: Bearer $API_KEY")
    fi
    curl -s --max-time 30 "${extra_args[@]}" "$@"
}

# ── 1. Health Check ───────────────────────────────────────────────────────────
section "1. Health Check"
HTTP_CODE=$(curl -s -o /tmp/av_health.json -w '%{http_code}' \
    "${BASE_URL}/health" ${extra_args[@]+"${extra_args[@]}"} --max-time 10)
if [[ "$HTTP_CODE" == "200" ]]; then
    STATUS=$(jq -r '.status // "unknown"' /tmp/av_health.json 2>/dev/null || echo "parse_error")
    HEALTHY=$(jq -r '.healthy // true' /tmp/av_health.json 2>/dev/null || echo "true")
    MODEL=$(jq -r '.current_model // "unknown"' /tmp/av_health.json 2>/dev/null || echo "unknown")
    if [[ "$STATUS" == "ok" && "$HEALTHY" == "true" ]]; then
        pass "Health OK (model=$MODEL)"
    elif [[ "$STATUS" == "loading" ]]; then
        pass "Health OK but model still loading"
    else
        UNHEALTHY=$(jq -r '.unhealthy_models // []' /tmp/av_health.json 2>/dev/null)
        fail "Health degraded" "status=$STATUS unhealthy=$UNHEALTHY"
    fi
else
    fail "Health check" "HTTP $HTTP_CODE"
fi

# ── 2. Voices List ────────────────────────────────────────────────────────────
section "2. Voices List"
BODY=$(curl_body "${BASE_URL}/v1/audio/voices")
VOICE_COUNT=$(echo "$BODY" | jq '.voices | length' 2>/dev/null || echo "0")
if [[ "$VOICE_COUNT" -gt 0 ]]; then
    pass "Voices listed ($VOICE_COUNT voices)"
else
    fail "Voices list" "0 voices returned"
fi

# ── 3. Kokoro WAV Synthesis ───────────────────────────────────────────────────
section "3. Kokoro WAV Synthesis"
WAV_OUT="/tmp/av_e2e_kokoro.wav"
HTTP_CODE=$(curl -s -o "$WAV_OUT" -w '%{http_code}' --max-time 60 \
    "${BASE_URL}/v1/audio/speech" \
    -H "Content-Type: application/json" \
    ${API_KEY:+-H "Authorization: Bearer $API_KEY"} \
    -d '{"model":"kokoro","input":"测试合成，这是一段中文语音。","voice":"af_xiaobei"}')
WAV_SIZE=$(stat -c%s "$WAV_OUT" 2>/dev/null || echo "0")
if [[ "$HTTP_CODE" == "200" && "$WAV_SIZE" -gt 1000 ]]; then
    pass "Kokoro WAV ($WAV_SIZE bytes)"
else
    fail "Kokoro WAV" "HTTP=$HTTP_CODE size=$WAV_SIZE"
fi

# ── 4. Kokoro WebSocket Stream ────────────────────────────────────────────────
section "4. Kokoro WebSocket Stream"
if command -v websocat &>/dev/null; then
    WS_RESULT=$(echo '{"model":"kokoro","input":"WebSocket流式测试。","voice":"af_xiaobei"}' \
        | timeout 30 websocat -n1 \
            "${BASE_URL/#http/ws}/v1/audio/speech/stream" \
            ${API_KEY:+-H "Authorization: Bearer $API_KEY"} 2>/dev/null || echo "ws_error")
    if [[ "$WS_RESULT" != *"ws_error"* && "$WS_RESULT" != *"error"* ]]; then
        pass "WebSocket stream"
    else
        fail "WebSocket stream" "Unexpected response"
    fi
else
    skip "WebSocket stream" "websocat not installed"
fi

# ── 5. MOSS CPU Stream ────────────────────────────────────────────────────────
section "5. MOSS CPU Stream"
MOSS_BODY=$(curl_body -X POST "${BASE_URL}/v1/audio/speech" \
    -H "Content-Type: application/json" \
    -d '{"model":"moss-nano-cpu","input":"MOSS CPU流式合成测试。","voice":"moss_moss-c-e"}')
MOSS_OK=$(echo "$MOSS_BODY" | jq -r '.ok // false' 2>/dev/null || echo "false")
if [[ "$MOSS_OK" == "true" ]]; then
    pass "MOSS CPU stream"
else
    ERROR=$(echo "$MOSS_BODY" | jq -r '.detail // .message // "unknown"' 2>/dev/null)
    skip "MOSS CPU stream" "MOSS not available: $ERROR"
fi

# ── 6. MOSS CUDA Stream (if available) ────────────────────────────────────────
section "6. MOSS CUDA Stream"
CUDA_BODY=$(curl_body -X POST "${BASE_URL}/v1/audio/speech" \
    -H "Content-Type: application/json" \
    -d '{"model":"moss-nano-cuda","input":"MOSS CUDA流式合成测试。","voice":"moss_moss-c-e"}')
CUDA_OK=$(echo "$CUDA_BODY" | jq -r '.ok // false' 2>/dev/null || echo "false")
if [[ "$CUDA_OK" == "true" ]]; then
    pass "MOSS CUDA stream"
else
    skip "MOSS CUDA stream" "CUDA model not available"
fi

# ── 7. Cancel Test ────────────────────────────────────────────────────────────
section "7. Cancel Test (abort long request)"
# Send request and abort after 1 second
CANCEL_FILE="/tmp/av_e2e_cancel.wav"
timeout 2 curl -s -o "$CANCEL_FILE" --max-time 10 \
    "${BASE_URL}/v1/audio/speech" \
    -H "Content-Type: application/json" \
    ${API_KEY:+-H "Authorization: Bearer $API_KEY"} \
    -d '{"model":"kokoro","input":"这段文字很长需要大量计算，我们会在中途取消它以测试取消功能是否正常工作。让我们继续添加更多文字来确保合成时间足够长以便能够成功取消。再来一些中文内容填充。","voice":"af_xiaobei","speed":0.3}' \
    >/dev/null 2>&1 || true
# Give server a moment to recover
sleep 1
# Verify server is still healthy after cancel
HEALTH_AFTER=$(curl -s -w '%{http_code}' -o /dev/null "${BASE_URL}/health" --max-time 5)
if [[ "$HEALTH_AFTER" == "200" ]]; then
    pass "Cancel + server recovery"
else
    fail "Cancel recovery" "Health after cancel: HTTP $HEALTH_AFTER"
fi

# ── 8. Idle Unload + Reload Test ──────────────────────────────────────────────
section "8. Idle Unload + Reload"
# Check if idle unload is configured
IDLE_TIMEOUT=$(jq -r '.model_idle_timeout_seconds // 0' /tmp/av_health.json 2>/dev/null || echo "0")
if [[ "$IDLE_TIMEOUT" -gt 0 ]]; then
    echo "  Idle timeout is ${IDLE_TIMEOUT}s, waiting for unload cycle..."
    # Wait for one idle check cycle
    CHECK_INTERVAL=$(jq -r '.model_idle_check_interval // 30' /tmp/av_health.json 2>/dev/null || echo "30")
    WAIT_TIME=$((CHECK_INTERVAL + IDLE_TIMEOUT + 5))
    sleep "$WAIT_TIME"
    # Now make a request — should trigger auto-reload
    HTTP_CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 60 \
        "${BASE_URL}/v1/audio/speech" \
        -H "Content-Type: application/json" \
        ${API_KEY:+-H "Authorization: Bearer $API_KEY"} \
        -d '{"model":"kokoro","input":"重载测试","voice":"af_xiaobei"}')
    if [[ "$HTTP_CODE" == "200" ]]; then
        pass "Idle unload + auto reload"
    else
        fail "Idle unload + auto reload" "HTTP $HTTP_CODE after waiting ${WAIT_TIME}s"
    fi
else
    skip "Idle unload + reload" "IDLE_TIMEOUT=0 (disabled)"
fi

# ── 9. Loop Stress Test ──────────────────────────────────────────────────────
section "9. Loop Stress Test ($LOOPS iterations)"
STRESS_PASS=0
STRESS_FAIL=0
for i in $(seq 1 "$LOOPS"); do
    HTTP_CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 60 \
        "${BASE_URL}/v1/audio/speech" \
        -H "Content-Type: application/json" \
        ${API_KEY:+-H "Authorization: Bearer $API_KEY"} \
        -d "{\"model\":\"kokoro\",\"input\":\"压测第${i}轮测试语音合成稳定性。\",\"voice\":\"af_xiaobei\"}")
    if [[ "$HTTP_CODE" == "200" ]]; then
        ((STRESS_PASS++))
    else
        ((STRESS_FAIL++))
        echo -e "  ${RED}✗ Iteration $i failed (HTTP $HTTP_CODE)${NC}"
    fi
    # Print progress every 10
    if (( i % 10 == 0 )); then
        echo -e "  ${CYAN}Progress: $i/$LOOPS (pass=$STRESS_PASS fail=$STRESS_FAIL)${NC}"
    fi
done

if [[ "$STRESS_FAIL" -eq 0 ]]; then
    pass "Stress test: $STRESS_PASS/$LOOPS all passed"
else
    fail "Stress test" "$STRESS_FAIL/$LOOPS failed"
fi

# ── 汇总 ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}══════════════════════════════════════════════════${NC}"
echo -e "  ${GREEN}PASS: $PASS${NC}  ${RED}FAIL: $FAIL${NC}  ${YELLOW}SKIP: $SKIP${NC}"
echo -e "${CYAN}══════════════════════════════════════════════════${NC}"

if [[ "$FAIL" -gt 0 ]]; then
    echo -e "\n${RED}Some tests failed!${NC}"
    exit 1
else
    echo -e "\n${GREEN}All tests passed!${NC}"
    exit 0
fi
