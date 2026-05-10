#!/usr/bin/env bash
# AngeVoice 一键安装脚本
# 自动检测 Docker、Compose、GPU 与网络情况，并推荐 CPU/GPU/legacy-gpu 画像。

set -euo pipefail

REPO_URL_DEFAULT="https://github.com/ang77712829/AngeVoice.git"
INSTALL_DIR_DEFAULT="/opt/angevoice"
PROFILE="auto"
INSTALL_DIR="$INSTALL_DIR_DEFAULT"
REPO_URL="$REPO_URL_DEFAULT"
NON_INTERACTIVE="false"

usage() {
  cat <<'EOF'
用法：
  bash scripts/install.sh [选项]

选项：
  --dir PATH          安装目录，默认 /opt/angevoice
  --repo URL          仓库地址，默认官方 GitHub
  --profile NAME      cpu | gpu | legacy-gpu | auto，默认 auto
  --yes               非交互模式，使用推荐配置
  -h, --help          查看帮助
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir) INSTALL_DIR="$2"; shift 2 ;;
    --repo) REPO_URL="$2"; shift 2 ;;
    --profile) PROFILE="$2"; shift 2 ;;
    --yes) NON_INTERACTIVE="true"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "未知参数：$1" >&2; usage; exit 2 ;;
  esac
done

log() { printf '\033[0;36m[AngeVoice]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[WARN]\033[0m %s\n' "$*"; }
fail() { printf '\033[0;31m[ERROR]\033[0m %s\n' "$*" >&2; exit 1; }

need_cmd() { command -v "$1" >/dev/null 2>&1 || return 1; }

check_docker() {
  need_cmd docker || fail "未检测到 docker，请先安装 Docker Engine。"
  docker compose version >/dev/null 2>&1 || fail "未检测到 docker compose v2，请安装 Docker Compose 插件。"
}

check_network() {
  local github_ok="no" ghcr_ok="no"
  if curl -fsSL --connect-timeout 5 --max-time 8 https://github.com >/dev/null 2>&1; then github_ok="yes"; fi
  if curl -fsSL --connect-timeout 5 --max-time 8 https://ghcr.io/v2/ >/dev/null 2>&1; then ghcr_ok="yes"; fi
  log "网络检测：GitHub=${github_ok} GHCR=${ghcr_ok}"
  if [[ "$github_ok" != "yes" ]]; then
    warn "访问 GitHub 较差：建议使用代理、镜像源或手动上传源码包。"
  fi
  if [[ "$ghcr_ok" != "yes" ]]; then
    warn "访问 ghcr.io 较差：首次拉取镜像可能失败，脚本会优先尝试本地构建。"
  fi
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
  local name
  name="$(detect_gpu_name | tr '[:upper:]' '[:lower:]')"
  case "$name" in
    *p4*|*p40*|*v100*|*1080*|*1070*|*1060*) echo "legacy-gpu" ;;
    *) echo "gpu" ;;
  esac
}

ensure_repo() {
  if [[ -d "$INSTALL_DIR/.git" ]]; then
    log "检测到已有仓库：$INSTALL_DIR"
    git -C "$INSTALL_DIR" fetch --all --prune || warn "git fetch 失败，将继续使用现有代码。"
    git -C "$INSTALL_DIR" pull --ff-only || warn "git pull 失败，将继续使用现有代码。"
    return
  fi
  mkdir -p "$(dirname "$INSTALL_DIR")"
  git clone "$REPO_URL" "$INSTALL_DIR"
}

prepare_config() {
  cd "$INSTALL_DIR"
  if [[ ! -f docker/angevoice.env ]]; then
    fail "缺少 docker/angevoice.env，请确认仓库完整。"
  fi
  log "默认配置文件：$INSTALL_DIR/docker/angevoice.env"
  if [[ "$NON_INTERACTIVE" != "true" ]]; then
    read -r -p "是否开启管理后台？需要设置账号密码 [y/N]: " ans
    if [[ "$ans" =~ ^[Yy]$ ]]; then
      read -r -p "后台用户名 [admin]: " admin_user
      admin_user="${admin_user:-admin}"
      read -r -s -p "后台密码: " admin_pass; echo
      [[ -n "$admin_pass" ]] || fail "后台密码不能为空。"
      sed -i 's/^KOKORO_ADMIN_ENABLED=.*/KOKORO_ADMIN_ENABLED=true/' docker/angevoice.env
      sed -i "s/^ANGEVOICE_ADMIN_USERNAME=.*/ANGEVOICE_ADMIN_USERNAME=${admin_user}/" docker/angevoice.env
      if grep -q '^# ANGEVOICE_ADMIN_PASSWORD=' docker/angevoice.env; then
        sed -i "s|^# ANGEVOICE_ADMIN_PASSWORD=.*|ANGEVOICE_ADMIN_PASSWORD=${admin_pass}|" docker/angevoice.env
      elif grep -q '^ANGEVOICE_ADMIN_PASSWORD=' docker/angevoice.env; then
        sed -i "s|^ANGEVOICE_ADMIN_PASSWORD=.*|ANGEVOICE_ADMIN_PASSWORD=${admin_pass}|" docker/angevoice.env
      else
        printf '\nANGEVOICE_ADMIN_PASSWORD=%s\n' "$admin_pass" >> docker/angevoice.env
      fi
    fi
  fi
}

run_compose() {
  local profile="$1" compose_dir
  case "$profile" in
    cpu) compose_dir="docker/cpu" ;;
    gpu) compose_dir="docker/gpu" ;;
    legacy-gpu) compose_dir="docker/legacy-gpu" ;;
    *) fail "未知画像：$profile" ;;
  esac
  log "推荐/选择画像：$profile"
  log "启动目录：$INSTALL_DIR/$compose_dir"
  cd "$INSTALL_DIR/$compose_dir"
  if docker compose pull; then
    docker compose up -d
  else
    warn "镜像拉取失败，将尝试本地构建。"
    docker compose up -d --build
  fi
}

main() {
  check_docker
  check_network
  local profile
  profile="$(recommend_profile)"
  if [[ "$NON_INTERACTIVE" != "true" ]]; then
    log "检测到 GPU：$(detect_gpu_name || true)"
    read -r -p "使用画像 [$profile]，可输入 cpu/gpu/legacy-gpu 覆盖: " chosen
    profile="${chosen:-$profile}"
  fi
  ensure_repo
  prepare_config
  run_compose "$profile"
  log "安装完成。"
  case "$profile" in
    cpu) log "访问：http://服务器IP:8100" ;;
    gpu) log "访问：http://服务器IP:8101" ;;
    legacy-gpu) log "访问：http://服务器IP:8102" ;;
  esac
  log "配置文件：$INSTALL_DIR/docker/angevoice.env"
}

main
