#!/usr/bin/env bash
# Docker/profile helpers for scripts/install.sh.

check_docker() {
  need_cmd docker || fail "未检测到 docker，请先安装 Docker Engine。"
  docker compose version >/dev/null 2>&1 || fail "未检测到 docker compose v2，请安装 Docker Compose 插件。"
}

has_nvidia_gpu() {
  command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1
}

detect_gpu_name() {
  if has_nvidia_gpu; then
    nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -n1 || true
  fi
}

recommend_profile() {
  if [[ "$PROFILE" != "auto" ]]; then
    echo "$PROFILE"; return
  fi
  if ! has_nvidia_gpu; then
    echo "cpu"; return
  fi
  # 默认只要检测到 NVIDIA GPU，就优先推荐通用 gpu 画像。
  # legacy-gpu 是 CUDA 11.8 兼容画像，仅在 gpu 画像无法启动或运行不稳定时再尝试。
  echo "gpu"
}

is_legacy_gpu_candidate() {
  local name
  name="$(detect_gpu_name | tr '[:upper:]' '[:lower:]')"
  case "$name" in
    *p4*|*p40*|*v100*|*1080*|*1070*|*1060*) return 0 ;;
    *) return 1 ;;
  esac
}


compose_dir_for_profile() {
  case "$1" in
    cpu) echo "docker/cpu" ;;
    gpu) echo "docker/gpu" ;;
    legacy-gpu) echo "docker/legacy-gpu" ;;
    *) fail "未知画像：$1" ;;
  esac
}

profile_for_container_name() {
  case "$1" in
    angevoice-cpu) echo "cpu" ;;
    angevoice-gpu) echo "gpu" ;;
    angevoice-legacy-gpu) echo "legacy-gpu" ;;
    *) echo "" ;;
  esac
}

port_for_profile() {
  case "$1" in
    cpu) echo "8100" ;;
    gpu) echo "8101" ;;
    legacy-gpu) echo "8102" ;;
    *) echo "8000" ;;
  esac
}
