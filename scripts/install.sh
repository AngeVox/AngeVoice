#!/usr/bin/env bash
# AngeVoice 一键安装与管理脚本
# 自动检测 Docker、Compose、GPU、镜像网络，并推荐 CPU/GPU 画像；legacy-gpu 作为兼容兜底。

set -euo pipefail

REPO_URL_DEFAULT="https://github.com/ang77712829/AngeVoice.git"
FALLBACK_INSTALL_DIR="/opt/angevoice"
SHORTCUT_NAME="AngeVoice"
PROFILE="auto"
REPO_URL="$REPO_URL_DEFAULT"
NON_INTERACTIVE="false"
INSTALL_DIR=""
INSTALL_DIR_SET_BY_USER="false"
ACTION="auto"
GHCR_OK="unknown"
DOCKERHUB_OK="unknown"
GITHUB_OK="unknown"
REGISTRY_MIRRORS=""

ORIGINAL_ARGS=("$@")
SCRIPT_SOURCE="${BASH_SOURCE[0]:-$0}"
if [[ "$SCRIPT_SOURCE" == */* ]]; then
  SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_SOURCE")" 2>/dev/null && pwd -P || pwd -P)"
else
  SCRIPT_DIR="$(pwd -P)"
fi
PWD_DIR="$(pwd -P)"

_bootstrap_is_project_root() {
  [[ -f "$1/docker/angevoice.env" && -d "$1/docker" && -d "$1/scripts/install/lib" ]]
}

_bootstrap_exec_full_repo() {
  local target="${INSTALL_DIR:-$FALLBACK_INSTALL_DIR}"
  printf '[0;36m[AngeVoice][0m 检测到远程单文件执行模式，正在准备完整安装脚本：%s
' "$target"
  command -v git >/dev/null 2>&1 || {
    printf '[0;31m[ERROR][0m 当前执行方式需要 git 自动拉取完整仓库，请先安装 git，或改用 git clone 后运行 scripts/install.sh。
' >&2
    exit 1
  }
  if [[ -d "$target/.git" ]]; then
    git -C "$target" fetch --all --prune || true
    git -C "$target" restore --staged . 2>/dev/null || true
    git -C "$target" restore . 2>/dev/null || true
    git -C "$target" clean -fd 2>/dev/null || true
    git -C "$target" pull --ff-only || true
  elif [[ -e "$target" && -n "$(find "$target" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]; then
    printf '[0;31m[ERROR][0m 安装目录已存在但不是 AngeVoice git 仓库：%s
' "$target" >&2
    printf '请使用 --dir 指定空目录/已有 AngeVoice 仓库，或手动清理该目录。
' >&2
    exit 1
  else
    mkdir -p "$(dirname "$target")"
    git clone "$REPO_URL" "$target"
  fi
  if [[ ! -f "$target/scripts/install.sh" ]]; then
    printf '[0;31m[ERROR][0m 完整仓库中仍找不到 scripts/install.sh：%s
' "$target" >&2
    exit 1
  fi
  exec bash "$target/scripts/install.sh" "${ORIGINAL_ARGS[@]}"
}
usage() {
  cat <<'USAGE'
用法：
  bash scripts/install.sh [选项]
  AngeVoice                 # 安装完成后可用的管理命令

选项：
  --dir PATH          安装目录；在源码目录内运行时默认使用当前项目，不再克隆到 /opt
  --repo URL          仓库地址，默认官方 GitHub
  --profile NAME      cpu | gpu | legacy-gpu | auto，默认 auto
  --yes               非交互模式，使用推荐配置
  --menu              显示管理菜单
  --status            显示当前容器和访问地址
  --restart           重启已安装画像
  --stop              停止容器但保留网络/配置
  --uninstall         停止并移除 AngeVoice 容器/网络，不删除模型、输出和配置文件
  --reinstall         跳过运行中服务菜单，直接安装/更新
  -h, --help          查看帮助
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir) INSTALL_DIR="$2"; INSTALL_DIR_SET_BY_USER="true"; shift 2 ;;
    --repo) REPO_URL="$2"; shift 2 ;;
    --profile) PROFILE="$2"; shift 2 ;;
    --yes) NON_INTERACTIVE="true"; shift ;;
    --menu) ACTION="menu"; shift ;;
    --status) ACTION="status"; shift ;;
    --restart) ACTION="restart"; shift ;;
    --stop) ACTION="stop"; shift ;;
    --uninstall) ACTION="uninstall"; shift ;;
    --reinstall) ACTION="install"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "未知参数：$1" >&2; usage; exit 2 ;;
  esac
done

INSTALL_LIB_DIR="${SCRIPT_DIR}/install/lib"
if [[ ! -f "${INSTALL_LIB_DIR}/common.sh" ]]; then
  if _bootstrap_is_project_root "$PWD_DIR"; then
    # 支持 bash <(curl ...install.sh) 在已克隆源码目录内执行。
    INSTALL_LIB_DIR="${PWD_DIR}/scripts/install/lib"
  elif [[ -n "$INSTALL_DIR" && -f "${INSTALL_DIR}/scripts/install/lib/common.sh" ]]; then
    INSTALL_LIB_DIR="${INSTALL_DIR}/scripts/install/lib"
  else
    # 远程 raw 一键脚本没有旁边的 lib 模块，自动拉取完整仓库后交给本地脚本继续执行。
    _bootstrap_exec_full_repo
  fi
fi
for module in common.sh docker.sh network.sh; do
  if [[ -f "${INSTALL_LIB_DIR}/${module}" ]]; then
    # shellcheck source=/dev/null
    source "${INSTALL_LIB_DIR}/${module}"
  else
    printf '[0;31m[ERROR][0m 缺少安装脚本模块：%s
' "${INSTALL_LIB_DIR}/${module}" >&2
    exit 1
  fi
done
detect_install_dir() {
  if [[ -n "$INSTALL_DIR" ]]; then
    printf '%s\n' "$INSTALL_DIR"
    return
  fi
  if is_project_root "$PWD_DIR"; then
    printf '%s\n' "$PWD_DIR"
    return
  fi
  local script_root
  script_root="$(project_root_from_script)"
  if [[ -n "$script_root" ]] && is_project_root "$script_root"; then
    printf '%s\n' "$script_root"
    return
  fi
  printf '%s\n' "$FALLBACK_INSTALL_DIR"
}

running_angevoice_containers() {
  docker ps --format '{{.Names}}' | grep -E '^angevoice-(cpu|gpu|legacy-gpu)$' || true
}

all_angevoice_containers() {
  docker ps -a --format '{{.Names}}' | grep -E '^angevoice-(cpu|gpu|legacy-gpu)$' || true
}

detect_active_profile() {
  local container profile
  container="$(running_angevoice_containers | head -n1 || true)"
  if [[ -z "$container" ]]; then
    container="$(all_angevoice_containers | head -n1 || true)"
  fi
  profile="$(profile_for_container_name "$container")"
  if [[ -n "$profile" ]]; then
    echo "$profile"
  else
    recommend_profile
  fi
}

ensure_repo() {
  if is_project_root "$INSTALL_DIR"; then
    log "使用当前项目目录：$INSTALL_DIR"
    if [[ -d "$INSTALL_DIR/.git" && "$INSTALL_DIR_SET_BY_USER" == "true" ]]; then
      git -C "$INSTALL_DIR" fetch --all --prune || warn "git fetch 失败，将继续使用现有代码。"
      git -C "$INSTALL_DIR" restore --staged . 2>/dev/null || true
      git -C "$INSTALL_DIR" restore . 2>/dev/null || true
      git -C "$INSTALL_DIR" clean -fd 2>/dev/null || true
      git -C "$INSTALL_DIR" pull --ff-only || warn "git pull 失败，将继续使用现有代码。"
    fi
    return
  fi
  if [[ -d "$INSTALL_DIR/.git" ]]; then
    log "检测到已有仓库：$INSTALL_DIR"
    git -C "$INSTALL_DIR" fetch --all --prune || warn "git fetch 失败，将继续使用现有代码。"
    git -C "$INSTALL_DIR" restore --staged . 2>/dev/null || true
    git -C "$INSTALL_DIR" restore . 2>/dev/null || true
    git -C "$INSTALL_DIR" clean -fd 2>/dev/null || true
    git -C "$INSTALL_DIR" pull --ff-only || warn "git pull 失败，将继续使用现有代码。"
    return
  fi
  mkdir -p "$(dirname "$INSTALL_DIR")"
  git clone "$REPO_URL" "$INSTALL_DIR"
}

install_shortcut() {
  local script_path target wrapper_dir
  script_path="$INSTALL_DIR/scripts/install.sh"
  [[ -f "$script_path" ]] || return 0
  if [[ -w "/usr/local/bin" || "$(id -u)" == "0" ]]; then
    target="/usr/local/bin/${SHORTCUT_NAME}"
  else
    wrapper_dir="$HOME/.local/bin"
    mkdir -p "$wrapper_dir"
    target="$wrapper_dir/${SHORTCUT_NAME}"
  fi
  cat > "$target" <<EOF_WRAPPER
#!/usr/bin/env bash
exec bash "${script_path}" --dir "${INSTALL_DIR}" --menu "\$@"
EOF_WRAPPER
  chmod +x "$target"
  log "管理命令已安装：$target"
  if [[ "$target" == "$HOME/.local/bin/${SHORTCUT_NAME}" ]]; then
    warn "如提示找不到 ${SHORTCUT_NAME}，请把 $HOME/.local/bin 加入 PATH。"
  fi
}


prepare_model_dirs() {
  cd "$INSTALL_DIR"
  mkdir -p \
    models/models--hexgrad--Kokoro-82M-v1.1-zh/voices \
    models/MOSS-TTS-Nano-100M-ONNX \
    models/MOSS-Audio-Tokenizer-Nano-ONNX \
    models/modelscope-cache \
    models/.hf \
    outputs

  # 旧版本把 HF 缓存和 MOSS 模型拆在 hf_cache / moss_models。若检测到旧目录，
  # 在新目录为空时做一次温和迁移，避免用户升级后重复下载大模型。
  if [[ -d hf_cache/hub/models--hexgrad--Kokoro-82M-v1.1-zh && ! -e models/models--hexgrad--Kokoro-82M-v1.1-zh/blobs ]]; then
    log "迁移旧 Hugging Face 缓存：hf_cache/hub/models--hexgrad--Kokoro-82M-v1.1-zh -> models/models--hexgrad--Kokoro-82M-v1.1-zh"
    cp -a hf_cache/hub/models--hexgrad--Kokoro-82M-v1.1-zh/. models/models--hexgrad--Kokoro-82M-v1.1-zh/ || warn "旧 HF 缓存迁移失败，可忽略并让服务重新下载。"
  fi
  if [[ -d moss_models && -z "$(find models/MOSS-TTS-Nano-100M-ONNX -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]; then
    log "迁移旧 MOSS 模型目录：moss_models -> models/MOSS-TTS-Nano-100M-ONNX"
    cp -a moss_models/. models/MOSS-TTS-Nano-100M-ONNX/ || warn "旧 MOSS 模型迁移失败，可忽略并让服务重新下载。"
  fi
  if [[ -d moss_audio_tokenizer && -z "$(find models/MOSS-Audio-Tokenizer-Nano-ONNX -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]; then
    log "迁移旧 MOSS Audio Tokenizer 目录：moss_audio_tokenizer -> models/MOSS-Audio-Tokenizer-Nano-ONNX"
    cp -a moss_audio_tokenizer/. models/MOSS-Audio-Tokenizer-Nano-ONNX/ || warn "旧 MOSS Audio Tokenizer 迁移失败，可忽略并让服务重新下载。"
  fi
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
      set_env_value docker/angevoice.env KOKORO_ADMIN_ENABLED true
      set_env_value docker/angevoice.env ANGEVOICE_ADMIN_USERNAME "$admin_user"
      set_env_value docker/angevoice.env ANGEVOICE_ADMIN_PASSWORD "$admin_pass"
    fi
  fi
}

choose_action_menu() {
  echo ""
  echo "AngeVoice 管理菜单"
  echo "  1) 安装/更新并启动"
  echo "  2) 重启当前画像"
  echo "  3) 停止容器（保留配置/数据）"
  echo "  4) 一键卸载（移除容器/网络，保留配置/数据）"
  echo "  5) 查看状态和访问地址"
  echo "  6) 退出"
  read -r -p "输入 [1/2/3/4/5/6，默认 5]: " action_choice
  case "${action_choice:-5}" in
    1) ACTION="install" ;;
    2) ACTION="restart" ;;
    3) ACTION="stop" ;;
    4) ACTION="uninstall" ;;
    5) ACTION="status" ;;
    6) exit 0 ;;
    *) ACTION="status" ;;
  esac
}

choose_action_if_running() {
  if [[ "$ACTION" == "menu" ]]; then
    choose_action_menu
    return
  fi
  if [[ "$ACTION" != "auto" || "$NON_INTERACTIVE" == "true" ]]; then
    return
  fi
  local running
  running="$(running_angevoice_containers)"
  if [[ -z "$running" ]]; then
    return
  fi
  echo "检测到正在运行的 AngeVoice 容器："
  echo "$running" | sed 's/^/  - /'
  choose_action_menu
}

compose_do_all_profiles() {
  local cmd="$1" found="false" dir
  cd "$INSTALL_DIR"
  for dir in docker/cpu docker/gpu docker/legacy-gpu; do
    if [[ -f "$dir/docker-compose.yml" ]]; then
      found="true"
      log "执行 ${cmd}：$dir"
      case "$cmd" in
        down) (cd "$dir" && docker compose down --remove-orphans) || warn "停止 $dir 失败，可能此前未启动。" ;;
        stop) (cd "$dir" && docker compose stop) || warn "停止 $dir 失败，可能此前未启动。" ;;
      esac
    fi
  done
  [[ "$found" == "true" ]] || warn "未找到 Docker Compose 配置目录。"
}

uninstall_all_profiles() {
  compose_do_all_profiles down
  log "卸载完成：容器和网络已停止/移除，模型、输出和配置文件已保留。"
  log "项目目录：$INSTALL_DIR"
}

stop_all_profiles() {
  compose_do_all_profiles stop
  log "停止完成：配置、模型和输出文件已保留。"
}

run_compose() {
  local profile="$1" compose_dir
  compose_dir="$(compose_dir_for_profile "$profile")"
  log "推荐/选择画像：$profile"
  log "启动目录：$INSTALL_DIR/$compose_dir"
  cd "$INSTALL_DIR/$compose_dir"
  if [[ "$GHCR_OK" == "yes" ]]; then
    if docker compose pull; then
      docker compose up -d
    else
      warn "镜像拉取失败，将尝试本地构建。"
      docker compose up -d --build
    fi
  else
    warn "GHCR 不可达，跳过 pull，直接本地构建。"
    docker compose up -d --build
  fi
}

restart_profile() {
  local profile="$1" compose_dir
  compose_dir="$(compose_dir_for_profile "$profile")"
  log "重启画像：$profile"
  cd "$INSTALL_DIR/$compose_dir"
  docker compose restart || docker compose up -d
}

print_api_key_hint() {
  local key_file="$INSTALL_DIR/outputs/.angevoice-api-key"
  if [[ -f "$key_file" ]]; then
    log "API Key 已自动生成：$key_file"
  else
    log "API Key 将在服务首次启动后自动生成：$key_file"
  fi
  log "查看 API Key：cat '$key_file'"
  log "复制该 token 到 Studio 设置里的 Bearer Token；如需网页查看/轮换，请开启 KOKORO_ADMIN_ENABLED=true 并设置 ANGEVOICE_ADMIN_PASSWORD。"
}

print_access_info() {
  local profile="$1" port ip
  port="$(port_for_profile "$profile")"
  ip="$(detect_host_ip)"
  log "访问：http://${ip}:${port}"
  log "管理后台：http://${ip}:${port}/admin"
  log "API 文档：http://${ip}:${port}/api-docs"
  log "配置文件：$INSTALL_DIR/docker/angevoice.env"
  print_api_key_hint
  log "管理命令：${SHORTCUT_NAME}"
}
print_status() {
  local profile
  profile="$(detect_active_profile)"
  log "项目目录：$INSTALL_DIR"
  log "当前/推荐画像：$profile"
  echo "容器状态："
  docker ps -a --filter "name=angevoice-" --format '  {{.Names}}	{{.Status}}	{{.Ports}}' || true
  print_access_info "$profile"
}

main() {
  INSTALL_DIR="$(detect_install_dir)"
  check_docker
  choose_action_if_running

  if [[ "$ACTION" == "status" ]]; then
    print_status
    exit 0
  fi
  if [[ "$ACTION" == "stop" ]]; then
    stop_all_profiles
    exit 0
  fi
  if [[ "$ACTION" == "uninstall" ]]; then
    if ! is_project_root "$INSTALL_DIR" && [[ ! -d "$INSTALL_DIR" ]]; then
      fail "未找到安装目录：$INSTALL_DIR。可使用 --dir 指定项目目录。"
    fi
    uninstall_all_profiles
    exit 0
  fi

  check_network
  local profile
  profile="$(recommend_profile)"
  if [[ "$ACTION" == "restart" ]]; then
    profile="$(detect_active_profile)"
    restart_profile "$profile"
    print_access_info "$profile"
    exit 0
  fi

  if [[ "$NON_INTERACTIVE" != "true" ]]; then
    local gpu_name
    gpu_name="$(detect_gpu_name || true)"
    if [[ -n "$gpu_name" ]]; then
      log "检测到 NVIDIA GPU：$gpu_name"
      if is_legacy_gpu_candidate; then
        warn "默认推荐通用 gpu 画像；legacy-gpu 仅作为 gpu 无法启动/不稳定时的保底尝试。"
      fi
    else
      log "未检测到 NVIDIA GPU。"
    fi
    read -r -p "使用画像 [$profile]，可输入 cpu/gpu/legacy-gpu 覆盖: " chosen
    profile="${chosen:-$profile}"
  fi
  ensure_repo
  prepare_config
  prepare_model_dirs
  run_compose "$profile"
  install_shortcut
  log "安装完成。"
  print_access_info "$profile"
}

main
