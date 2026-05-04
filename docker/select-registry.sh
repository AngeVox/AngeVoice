#!/bin/bash
# select-registry.sh — 测试三个 registry 连通速度，选最快的写入 .env
# 用法: bash select-registry.sh [v2.4.0]

set -euo pipefail

VERSION="${1:-latest}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

registries=(
  "ghcr.io/ang77712829|GHCR (GitHub)"
  "docker.io/maxblack777|Docker Hub"
  "cr.ccs.tencentyun.com/angeangeange|CNB (腾讯云)"
)

echo "🔍 测试 registry 连通速度..."
echo ""

best_reg=""
best_time=999
best_label=""

for entry in "${registries[@]}"; do
  IFS='|' read -r url label <<< "$entry"

  # 用 curl 测 HTTPS 响应时间（只测 v2 API 头部）
  time_total=$(curl -s -o /dev/null -w "%{time_total}" \
    --connect-timeout 5 --max-time 10 \
    "https://${url}/v2/" 2>/dev/null || echo "999")

  # 转为毫秒比较
  time_ms=$(echo "$time_total * 1000" | bc 2>/dev/null | cut -d. -f1)
  [ -z "$time_ms" ] && time_ms=999

  if [ "$time_ms" -lt "$best_time" ]; then
    best_time=$time_ms
    best_reg=$url
    best_label=$label
  fi

  printf "  %-35s %sms\n" "$label" "$time_ms"
done

echo ""
echo "✅ 最快: $best_label (${best_time}ms)"
echo "REGISTRY=$best_reg" > "${SCRIPT_DIR}/.env"
echo "VERSION=$VERSION" >> "${SCRIPT_DIR}/.env"
echo "📝 已写入 ${SCRIPT_DIR}/.env"
echo ""
cat "${SCRIPT_DIR}/.env"
