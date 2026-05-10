#!/usr/bin/env bash
# AngeVoice 一键安装与管理脚本
# 自动检测 Docker、Compose、GPU、镜像网络，并推荐 CPU/GPU/legacy-gpu 画像。

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

SCRIPT_SOURCE="${BASH_SOURCE[0]:-$0}"
if [[ "$SCRIPT_SOURCE" == */* ]]; then
  SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_SOURCE")" 2>/dev/null && pwd -P || pwd -P)"
else
  SCRIPT_DIR="$(pwd -P)"
fi
PWD_DIR="$(pwd -P)"

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

log() { printf '\033[0;36m[AngeVoice]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[WARN]\033[0m %s\n' "$*"; }
fail() { printf '\033[0;31m[ERROR]\033[0m %s\n' "$*" >&2; exit 1; }

need_cmd() { command -v "$1" >/dev/null 2>&1 || return 1; }

escape_sed_replacement() {
  printf '%s' "$1" | sed -e 's/[\/&]/\\&/g'
}

set_env_value() {
  local file="$1" key="$2" value="$3" escaped
  escaped="$(escape_sed_replacement "$value")"
  if grep -q "^#\?${key}=" "$file"; then
    sed -i "s|^#\?${key}=.*|${key}=${escaped}|" "$file"
  else
    printf '\n%s=%s\n' "$key" "$value" >> "$file"
  fi
}

is_project_root() {
  [[ -f "$1/docker/angevoice.env" && -d "$1/docker" && -d "$1/scripts" ]]
}

project_root_from_script() {
  local candidate
  candidate="$(cd "$SCRIPT_DIR/.." 2>/dev/null && pwd -P || true)"
  if [[ -n "$candidate" && -d "$candidate" ]]; then
    printf '%s\n' "$candidate"
  fi
}

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

check_docker() {
  need_cmd docker || fail "未检测到 docker，请先安装 Docker Engine。"
  docker compose version >/dev/null 2>&1 || fail "未检测到 docker compose v2，请安装 Docker Compose 插件。"
}

_check_url() {
  local url="$1"
  curl -fsSL --connect-timeout 5 --max-time 8 "$url" >/dev/null 2>&1
}

_check_url_allow_http_error() {
  local url="$1" code
  code="$(curl -k -sS -o /dev/null -w '%{http_code}' --connect-timeout 5 --max-time 8 "$url" 2>/dev/null || true)"
  [[ "$code" =~ ^(200|301|302|401)$ ]]
}

_detect_registry_mirrors() {
  local file="/etc/docker/daemon.json"
  REGISTRY_MIRRORS=""
  if [[ -f "$file" ]]; then
    REGISTRY_MIRRORS="$(grep -o 'https\?://[^" ,]\+' "$file" 2>/dev/null | tr '\n' ' ' | sed 's/[[:space:]]*$//')"
  fi
}

check_network() {
  GITHUB_OK="no"
  GHCR_OK="no"
  DOCKERHUB_OK="no"
  _check_url https://github.com && GITHUB_OK="yes"
  _check_url_allow_http_error https://ghcr.io/v2/ && GHCR_OK="yes"
  _check_url_allow_http_error https://registry-1.docker.io/v2/ && DOCKERHUB_OK="yes"
  _detect_registry_mirrors
  log "网络检测：GitHub=${GITHUB_OK} GHCR=${GHCR_OK} DockerHub=${DOCKERHUB_OK}"
  if [[ -n "$REGISTRY_MIRRORS" ]]; then
    log "检测到 Docker registry mirror：$REGISTRY_MIRRORS"
  fi
  if [[ "$GITHUB_OK" != "yes" ]]; then
    warn "访问 GitHub 较差：建议使用代理、镜像源或手动上传源码包。"
  fi
  if [[ "$GHCR_OK" != "yes" ]]; then
    warn "访问 ghcr.io 较差：将跳过预构建镜像 pull，优先本地构建。"
  fi
  if [[ "$DOCKERHUB_OK" != "yes" && -z "$REGISTRY_MIRRORS" ]]; then
    warn "访问 Docker Hub 较差且未检测到 registry mirror；本地构建可能在拉基础镜像时较慢。"
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

detect_host_ip() {
  local ip=""
  if command -v ip >/dev/null 2>&1; then
    ip="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i=1;i<=NF;i++) if ($i=="src") {print $(i+1); exit}}')"
  fi
  if [[ -z "$ip" ]] && command -v hostname >/dev/null 2>&1; then
    ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
  fi
  printf '%s\n' "${ip:-127.0.0.1}"
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
      git -C "$INSTALL_DIR" pull --ff-only || warn "git pull 失败，将继续使用现有代码。"
    fi
    return
  fi
  if [[ -d "$INSTALL_DIR/.git" ]]; then
    log "检测到已有仓库：$INSTALL_DIR"
    git -C "$INSTALL_DIR" fetch --all --prune || warn "git fetch 失败，将继续使用现有代码。"
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

print_access_info() {
  local profile="$1" port ip
  port="$(port_for_profile "$profile")"
  ip="$(detect_host_ip)"
  log "访问：http://${ip}:${port}"
  log "管理后台：http://${ip}:${port}/admin"
  log "API 文档：http://${ip}:${port}/api-docs"
  log "配置文件：$INSTALL_DIR/docker/angevoice.env"
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
    log "检测到 GPU：$(detect_gpu_name || true)"
    read -r -p "使用画像 [$profile]，可输入 cpu/gpu/legacy-gpu 覆盖: " chosen
    profile="${chosen:-$profile}"
  fi
  ensure_repo
  prepare_config
  run_compose "$profile"
  install_shortcut
  log "安装完成。"
  print_access_info "$profile"
}

main
