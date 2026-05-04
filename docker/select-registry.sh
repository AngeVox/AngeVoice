#!/bin/bash
# select-registry.sh — 测试三个 registry 连通速度，选最快的写入 .env
# 用法: bash select-registry.sh

set -euo pipefail

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
  IFS="|" read -r url label <<< "$entry"

  time_total=$(curl -s -o /dev/null -w "%{time_total}" \
    --connect-timeout 5 --max-time 10 \
    "https://${url}/v2/" 2>/dev/null || echo "999")

  # 用 awk 替代 bc（更通用）
  time_ms=$(echo "$time_total" | awk '{printf "%d", $1 * 1000}')
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

# 写入各 profile 目录的 .env（Docker Compose 自动读取同目录 .env）
for profile in gpu cpu legacy-gpu; do
  env_file="${SCRIPT_DIR}/${profile}/.env"
  echo "REGISTRY=$best_reg" > "$env_file"
  echo "📝 已写入 $env_file"
done

echo ""
echo "现在可以 cd 到任意 profile 目录运行 docker compose up -d"
