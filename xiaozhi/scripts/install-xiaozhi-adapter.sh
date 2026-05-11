#!/usr/bin/env bash
set -Eeuo pipefail

REPO_RAW="https://raw.githubusercontent.com/ang77712829/AngeVoice/main/xiaozhi"

XIAOZHI_DIR=""
ANGEVOICE_HTTP=""
ANGEVOICE_WS=""
MODE=""
MODEL=""
API_KEY=""
PROMPT_AUDIO=""

PATCH_COMPOSE="ask"
WRITE_CONFIG="ask"
RESTART="ask"

YES="false"
DRY_RUN="false"

log() { printf '\033[1;32m[AngeVoice-xiaozhi]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[WARN]\033[0m %s\n' "$*" >&2; }
err() { printf '\033[1;31m[ERROR]\033[0m %s\n' "$*" >&2; }

usage() {
  cat <<'USAGE'
AngeVoice 小智后端适配器安装脚本

交互式安装：
  bash <(curl -fsSL https://raw.githubusercontent.com/ang77712829/AngeVoice/main/xiaozhi/scripts/install-xiaozhi-adapter.sh)

常用参数：
  --xiaozhi-dir DIR       小智 compose 文件所在目录
  --angevoice-url URL     AngeVoice HTTP 地址
  --angevoice-ws URL      AngeVoice WebSocket 地址
  --mode MODE             kokoro|kokoro-stream|moss|moss-stream|moss-clone|moss-clone-stream
  --model MODEL           kokoro|moss-nano-cpu|moss-nano-cuda
  --api-key KEY           AngeVoice API Key，未启用鉴权可留空
  --prompt-audio FILE     MOSS clone 参考音频，会复制为 data/angevoice_prompts/reference.wav

安装控制：
  --adapters-only         只安装适配器，不 patch compose，不写配置，不重启
  --no-compose            不修改 compose 文件
  --no-config             不写入 data/.config.yaml
  --no-restart            不重启 xiaozhi-esp32-server 容器
  --yes, -y               非交互模式，使用默认值
  --dry-run               只显示将要执行的操作

兼容 compose 文件名：
  docker-compose_all.yml / docker-compose.yml / compose.yml

示例：
  bash install-xiaozhi-adapter.sh --xiaozhi-dir /vol3/1000/docker/xiaozhi-server
  bash install-xiaozhi-adapter.sh --mode moss-clone-stream --prompt-audio ./reference.wav
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --xiaozhi-dir) XIAOZHI_DIR="$2"; shift 2 ;;
    --angevoice-url) ANGEVOICE_HTTP="${2%/}"; shift 2 ;;
    --angevoice-ws) ANGEVOICE_WS="$2"; shift 2 ;;
    --mode) MODE="$2"; shift 2 ;;
    --model) MODEL="$2"; shift 2 ;;
    --api-key) API_KEY="$2"; shift 2 ;;
    --prompt-audio) PROMPT_AUDIO="$2"; shift 2 ;;
    --adapters-only) PATCH_COMPOSE="false"; WRITE_CONFIG="false"; RESTART="false"; shift ;;
    --no-compose) PATCH_COMPOSE="false"; shift ;;
    --no-config) WRITE_CONFIG="false"; shift ;;
    --no-restart) RESTART="false"; shift ;;
    --yes|-y) YES="true"; shift ;;
    --dry-run) DRY_RUN="true"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) err "未知参数: $1"; usage; exit 1 ;;
  esac
done

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    err "缺少命令: $1"
    exit 1
  }
}

need_cmd curl
need_cmd sed
need_cmd python3

is_interactive() {
  [[ -t 0 && "$YES" != "true" ]]
}

ask_line() {
  local prompt="$1"
  local default="${2:-}"
  local value=""

  if is_interactive; then
    if [[ -n "$default" ]]; then
      printf "%s [%s]: " "$prompt" "$default" >&2
    else
      printf "%s: " "$prompt" >&2
    fi
    IFS= read -r value || true
    printf "%s" "${value:-$default}"
  else
    printf "%s" "$default"
  fi
}

ask_yes_no() {
  local prompt="$1"
  local default="${2:-Y}"
  local value=""
  local suffix="y/N"

  [[ "$default" =~ ^[Yy]$ ]] && suffix="Y/n"

  if is_interactive; then
    printf "%s [%s]: " "$prompt" "$suffix" >&2
    IFS= read -r value || true
    value="${value:-$default}"
  else
    value="$default"
  fi

  [[ "$value" =~ ^[Yy]$ ]]
}

compose_file_in_dir() {
  local dir="$1"
  local file

  for file in docker-compose_all.yml docker-compose.yml compose.yml; do
    if [[ -f "$dir/$file" ]]; then
      printf "%s" "$file"
      return 0
    fi
  done

  return 1
}

valid_compose_dir() {
  [[ -d "$1" ]] && compose_file_in_dir "$1" >/dev/null
}

is_likely_xiaozhi_dir() {
  local dir="$1"
  local compose_file=""
  local content=""

  valid_compose_dir "$dir" || return 1

  compose_file="$(compose_file_in_dir "$dir")"
  content="$(head -c 30000 "$dir/$compose_file" 2>/dev/null || true)"

  [[ "$dir" == *xiaozhi* ]] && return 0
  [[ -f "$dir/data/.config.yaml" ]] && return 0
  [[ "$content" == *xiaozhi-esp32-server* ]] && return 0
  [[ "$content" == */opt/xiaozhi-esp32-server* ]] && return 0
  [[ "$content" == *SenseVoiceSmall* ]] && return 0

  return 1
}

CANDIDATES=()

add_candidate() {
  local dir="$1"
  local existing

  [[ -n "$dir" && -d "$dir" ]] || return 0

  dir="$(cd "$dir" 2>/dev/null && pwd || true)"
  [[ -n "$dir" ]] || return 0

  is_likely_xiaozhi_dir "$dir" || return 0

  for existing in "${CANDIDATES[@]:-}"; do
    [[ "$existing" == "$dir" ]] && return 0
  done

  CANDIDATES+=("$dir")
  return 0
}

add_container_candidates() {
  command -v docker >/dev/null 2>&1 || return 0

  local name
  local mounts
  local source
  local dest

  while IFS= read -r name; do
    [[ -n "$name" ]] || continue

    mounts="$(docker inspect "$name" --format '{{range .Mounts}}{{println .Source "|" .Destination}}{{end}}' 2>/dev/null || true)"

    while IFS='|' read -r source dest; do
      [[ -n "${source:-}" && -n "${dest:-}" ]] || continue

      case "$dest" in
        */data)
          add_candidate "$(dirname "$source")"
          ;;
        /opt/xiaozhi-esp32-server)
          add_candidate "$source"
          ;;
      esac
    done <<< "$mounts"
  done < <(docker ps --format '{{.Names}}' 2>/dev/null | grep -Ei 'xiaozhi|esp32' || true)

  return 0
}

find_xiaozhi_dir() {
  if [[ -n "$XIAOZHI_DIR" ]]; then
    if valid_compose_dir "$XIAOZHI_DIR"; then
      cd "$XIAOZHI_DIR" && pwd
      return 0
    fi
    warn "传入目录没有 compose 文件: $XIAOZHI_DIR"
  fi

  local cur="$PWD"
  local root
  local file
  local dir

  while [[ "$cur" != "/" && -n "$cur" ]]; do
    add_candidate "$cur"
    cur="$(dirname "$cur")"
  done

  add_container_candidates

  for dir in \
    "$HOME/xiaozhi-server" \
    "$HOME/docker/xiaozhi-server" \
    "/opt/xiaozhi-server" \
    "/root/xiaozhi-server" \
    "/vol1/1000/docker/xiaozhi-server" \
    "/vol2/1000/docker/xiaozhi-server" \
    "/vol3/1000/docker/xiaozhi-server"; do
    add_candidate "$dir"
  done

  for root in /vol1 /vol2 /vol3 /volume1 /volume2 /mnt /srv /data; do
    [[ -d "$root" ]] || continue

    while IFS= read -r file; do
      add_candidate "$(dirname "$file")"
    done < <(
      find "$root" -maxdepth 5 \
        \( -name 'docker-compose_all.yml' -o -name 'docker-compose.yml' -o -name 'compose.yml' \) \
        2>/dev/null | head -n 50
    )
  done

  if [[ ${#CANDIDATES[@]} -eq 1 ]]; then
    printf "%s" "${CANDIDATES[0]}"
    return 0
  fi

  if [[ ${#CANDIDATES[@]} -gt 1 ]] && is_interactive; then
    echo "检测到多个可能的小智目录：" >&2

    local i=1
    for dir in "${CANDIDATES[@]}"; do
      echo "  $i) $dir ($(compose_file_in_dir "$dir"))" >&2
      i=$((i + 1))
    done

    local choice
    choice="$(ask_line "请选择编号，或直接输入自定义目录" "1")"

    if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= ${#CANDIDATES[@]} )); then
      printf "%s" "${CANDIDATES[$((choice - 1))]}"
      return 0
    fi

    if valid_compose_dir "$choice"; then
      cd "$choice" && pwd
      return 0
    fi
  fi

  if is_interactive; then
    local manual
    manual="$(ask_line "请输入小智 compose 文件所在目录" "$PWD")"

    if valid_compose_dir "$manual"; then
      cd "$manual" && pwd
      return 0
    fi
  fi

  err "未找到小智目录。目录内需有 docker-compose_all.yml / docker-compose.yml / compose.yml。可传 --xiaozhi-dir 指定。"
  exit 1
}

compose_cmd() {
  if docker compose version >/dev/null 2>&1; then
    echo "docker compose"
  elif command -v docker-compose >/dev/null 2>&1; then
    echo "docker-compose"
  else
    echo ""
  fi
}

DETECTED_AV_NAME=""
DETECTED_AV_PROFILE="cpu"
DETECTED_AV_MODELS=""
DETECTED_AV_PORT="8101"

detect_angevoice() {
  command -v docker >/dev/null 2>&1 || return 0

  local line=""
  local name=""
  local image=""
  local ports=""
  local envs=""

  line="$(docker ps --format '{{.Names}}|{{.Image}}|{{.Ports}}' 2>/dev/null | grep -i 'angevoice' | head -n 1 || true)"
  [[ -n "$line" ]] || return 0

  IFS='|' read -r name image ports <<< "$line"

  envs="$(docker inspect "$name" --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null || true)"

  DETECTED_AV_NAME="$name"
  DETECTED_AV_MODELS="$(printf '%s\n' "$envs" | sed -n 's/^ANGEVOICE_ENABLED_MODELS=//p' | head -n 1 || true)"

  if [[ "$name $image $ports $DETECTED_AV_MODELS" =~ (gpu|cuda) ]]; then
    DETECTED_AV_PROFILE="gpu"
  fi

  if [[ "$name $image $ports" =~ legacy ]]; then
    DETECTED_AV_PROFILE="legacy-gpu"
  fi

  if [[ "$ports" == *8102* ]]; then
    DETECTED_AV_PORT="8102"
  elif [[ "$ports" == *8101* ]]; then
    DETECTED_AV_PORT="8101"
  elif [[ "$ports" == *8100* ]]; then
    DETECTED_AV_PORT="8100"
  fi

  return 0
}

resolve_urls() {
  detect_angevoice || true

  if [[ -n "$DETECTED_AV_NAME" ]]; then
    log "检测到 AngeVoice 容器: $DETECTED_AV_NAME (${DETECTED_AV_PROFILE}, port ${DETECTED_AV_PORT}, models=${DETECTED_AV_MODELS:-unknown})"
  fi

  if [[ -z "$ANGEVOICE_HTTP" ]]; then
    ANGEVOICE_HTTP="http://host.docker.internal:${DETECTED_AV_PORT}"
  fi

  if is_interactive; then
    ANGEVOICE_HTTP="$(ask_line "AngeVoice HTTP 地址" "$ANGEVOICE_HTTP")"
  fi

  if [[ -z "$ANGEVOICE_WS" ]]; then
    if [[ "$ANGEVOICE_HTTP" == http://* ]]; then
      ANGEVOICE_WS="ws://${ANGEVOICE_HTTP#http://}/ws/v1/tts"
    elif [[ "$ANGEVOICE_HTTP" == https://* ]]; then
      ANGEVOICE_WS="wss://${ANGEVOICE_HTTP#https://}/ws/v1/tts"
    else
      ANGEVOICE_WS="ws://host.docker.internal:8101/ws/v1/tts"
    fi
  fi

  if is_interactive; then
    ANGEVOICE_WS="$(ask_line "AngeVoice WS 地址" "$ANGEVOICE_WS")"
  fi

  return 0
}

choose_mode() {
  [[ -n "$MODE" ]] && return 0

  if is_interactive; then
    echo >&2
    echo "请选择接入模式：" >&2
    echo "  1) Kokoro 流式，日常推荐" >&2
    echo "  2) Kokoro 非流式，最快跑通" >&2
    echo "  3) MOSS 预设音色流式" >&2
    echo "  4) MOSS 预设音色非流式" >&2
    echo "  5) MOSS 克隆流式，高级玩法" >&2
    echo "  6) MOSS 克隆非流式" >&2

    local choice
    choice="$(ask_line "输入编号" "1")"

    case "$choice" in
      1) MODE="kokoro-stream" ;;
      2) MODE="kokoro" ;;
      3) MODE="moss-stream" ;;
      4) MODE="moss" ;;
      5) MODE="moss-clone-stream" ;;
      6) MODE="moss-clone" ;;
      *) MODE="kokoro-stream" ;;
    esac
  else
    MODE="kokoro-stream"
  fi

  return 0
}

recommend_model() {
  case "$MODE" in
    kokoro*)
      echo "kokoro"
      ;;
    moss*)
      if [[ "$DETECTED_AV_MODELS" == *moss-nano-cuda* || "$DETECTED_AV_PROFILE" != "cpu" ]]; then
        echo "moss-nano-cuda"
      else
        echo "moss-nano-cpu"
      fi
      ;;
  esac
}

choose_model() {
  [[ -n "$MODEL" ]] && return 0

  MODEL="$(recommend_model)"

  if [[ "$MODE" == moss* ]] && is_interactive; then
    echo >&2
    echo "请选择 MOSS 模型：" >&2
    echo "  1) moss-nano-cpu，兼容性最好" >&2
    echo "  2) moss-nano-cuda，适合 AngeVoice GPU/legacy-gpu 容器" >&2

    local default="1"
    [[ "$MODEL" == "moss-nano-cuda" ]] && default="2"

    local choice
    choice="$(ask_line "输入编号" "$default")"

    if [[ "$choice" == "2" ]]; then
      MODEL="moss-nano-cuda"
    else
      MODEL="moss-nano-cpu"
    fi
  fi

  return 0
}

backup_file() {
  local file="$1"
  local backup=""

  [[ -f "$file" ]] || return 0

  backup="${file}.angevoice.$(date +%Y%m%d-%H%M%S).bak"

  if [[ "$DRY_RUN" == "true" ]]; then
    log "[dry-run] 将备份: $backup"
  else
    cp "$file" "$backup"
    log "已备份: $backup"
  fi
}

patch_compose() {
  local compose_file="$1"

  backup_file "$compose_file"

  if grep -q 'angevoice-adapter/angevoice.py' "$compose_file"; then
    log "$compose_file 已包含 AngeVoice 挂载，跳过 patch"
    return 0
  fi

  if [[ "$DRY_RUN" == "true" ]]; then
    log "[dry-run] 将 patch $compose_file"
    return 0
  fi

  python3 - "$compose_file" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
lines = path.read_text(encoding="utf-8").splitlines(True)

volumes = [
    "      # AngeVoice TTS adapters\n",
    "      - ./angevoice-adapter/angevoice.py:/opt/xiaozhi-esp32-server/core/providers/tts/angevoice.py:ro\n",
    "      - ./angevoice-adapter/angevoice_stream.py:/opt/xiaozhi-esp32-server/core/providers/tts/angevoice_stream.py:ro\n",
    "      - ./angevoice-adapter/angevoice_clone.py:/opt/xiaozhi-esp32-server/core/providers/tts/angevoice_clone.py:ro\n",
    "      # MOSS clone prompt audio directory\n",
    "      - ./data/angevoice_prompts:/opt/xiaozhi-esp32-server/data/angevoice_prompts:ro\n",
]

extra_hosts = [
    "    extra_hosts:\n",
    "      - \"host.docker.internal:host-gateway\"\n",
]

service_start = None

for i, line in enumerate(lines):
    if re.match(r"^  [A-Za-z0-9_.-]+:\s*$", line):
        block = "".join(lines[i:i + 140])
        if (
            "xiaozhi-esp32-server" in block
            or "/opt/xiaozhi-esp32-server" in block
            or "SenseVoiceSmall" in block
        ):
            service_start = i
            break

if service_start is None:
    raise SystemExit(
        "无法定位小智 server 服务，请手动参考 xiaozhi/examples/docker-compose.patch.example.yml"
    )

service_end = len(lines)

for j in range(service_start + 1, len(lines)):
    if re.match(r"^  [A-Za-z0-9_.-]+:\s*$", lines[j]):
        service_end = j
        break

service_text = "".join(lines[service_start:service_end])

if "host.docker.internal:host-gateway" not in service_text:
    insert_at = service_start + 1
    for j in range(service_start + 1, service_end):
        if re.match(
            r"^    (container_name|image|build|restart|networks|ports|volumes|environment|depends_on|security_opt):",
            lines[j],
        ):
            insert_at = j
            break
    lines[insert_at:insert_at] = extra_hosts
    service_end += len(extra_hosts)

service_text = "".join(lines[service_start:service_end])

if "angevoice-adapter/angevoice.py" not in service_text:
    volumes_line = None

    for j in range(service_start + 1, service_end):
        if re.match(r"^    volumes:\s*$", lines[j]):
            volumes_line = j
            break

    if volumes_line is None:
        lines[service_start + 1:service_start + 1] = ["    volumes:\n"] + volumes
    else:
        insert_at = volumes_line + 1
        for j in range(volumes_line + 1, service_end):
            if re.match(r"^    [A-Za-z0-9_.-]+:\s*", lines[j]):
                break
            insert_at = j + 1
        lines[insert_at:insert_at] = volumes

path.write_text("".join(lines), encoding="utf-8")
PY

  log "已 patch $compose_file"
}

write_config() {
  local selected="$1"
  local type="$2"
  local model="$3"
  local voice="$4"
  local format="$5"
  local timeout="$6"
  local prompt="$7"

  cat >> data/.config.yaml <<YAML

# ===== AngeVoice Xiaozhi adapter begin =====
# 如果你使用智控台，下面配置可能会被数据库配置覆盖；请优先在智控台里新增同名模型。
selected_module:
  TTS: ${selected}

TTS:
  ${selected}:
    type: ${type}
    api_url: $([[ "$type" == "angevoice" || "$type" == "angevoice_clone" ]] && echo "$ANGEVOICE_HTTP" || echo "$ANGEVOICE_WS")
    http_url: ${ANGEVOICE_HTTP}
    api_key: "${API_KEY}"
    model: ${model}
    voice: ${voice}
    format: ${format}
    response_format: wav
    speed: 1.0
    output_dir: tmp/
    tts_timeout: ${timeout}
YAML

  if [[ -n "$prompt" ]]; then
    cat >> data/.config.yaml <<'YAML'
    prompt_audio_path: /opt/xiaozhi-esp32-server/data/angevoice_prompts/reference.wav
    prompt_audio_filename: reference.wav
YAML
  fi

  cat >> data/.config.yaml <<'YAML'
# ===== AngeVoice Xiaozhi adapter end =====
YAML
}

config_tuple() {
  case "$MODE" in
    kokoro)
      echo "AngeVoiceKokoro|angevoice|kokoro|zm_010|wav|120|"
      ;;
    kokoro-stream)
      echo "AngeVoiceKokoroStream|angevoice_stream|kokoro|zm_010|pcm_s16le|180|"
      ;;
    moss)
      echo "AngeVoiceMoss|angevoice|${MODEL}|Junhao|wav|180|"
      ;;
    moss-stream)
      echo "AngeVoiceMossStream|angevoice_stream|${MODEL}|Junhao|pcm_s16le|240|"
      ;;
    moss-clone)
      echo "AngeVoiceMossClone|angevoice_clone|${MODEL}|Junhao|wav|300|prompt"
      ;;
    moss-clone-stream)
      echo "AngeVoiceMossCloneStream|angevoice_stream|${MODEL}|Junhao|pcm_s16le|300|prompt"
      ;;
  esac
}

XIAOZHI_DIR="$(find_xiaozhi_dir)"
cd "$XIAOZHI_DIR"

COMPOSE_FILE="$(compose_file_in_dir "$XIAOZHI_DIR")"

resolve_urls
choose_mode

case "$MODE" in
  kokoro|kokoro-stream|moss|moss-stream|moss-clone|moss-clone-stream)
    ;;
  *)
    err "不支持的 mode: $MODE"
    exit 1
    ;;
esac

choose_model

case "$MODEL" in
  kokoro|moss-nano-cpu|moss-nano-cuda)
    ;;
  *)
    err "不支持的 model: $MODEL"
    exit 1
    ;;
esac

if [[ "$MODE" == moss-clone* && -z "$PROMPT_AUDIO" ]] && is_interactive; then
  PROMPT_AUDIO="$(ask_line "MOSS clone 参考音频路径；留空则稍后手动放入 data/angevoice_prompts/reference.wav" "")"
fi

if [[ "$PATCH_COMPOSE" == "ask" ]]; then
  if ask_yes_no "是否修改 ${COMPOSE_FILE} 挂载适配器和 host.docker.internal" "Y"; then
    PATCH_COMPOSE="true"
  else
    PATCH_COMPOSE="false"
  fi
fi

if [[ "$WRITE_CONFIG" == "ask" ]]; then
  if ask_yes_no "是否写入 data/.config.yaml 示例配置；使用智控台的用户可选否" "Y"; then
    WRITE_CONFIG="true"
  else
    WRITE_CONFIG="false"
  fi
fi

if [[ "$RESTART" == "ask" ]]; then
  if ask_yes_no "是否重启 xiaozhi-esp32-server 容器" "Y"; then
    RESTART="true"
  else
    RESTART="false"
  fi
fi

log "小智目录: $XIAOZHI_DIR"
log "Compose 文件: $COMPOSE_FILE"
log "AngeVoice HTTP: $ANGEVOICE_HTTP"
log "AngeVoice WS: $ANGEVOICE_WS"
log "安装模式: $MODE"
log "模型: $MODEL"

if [[ "$DRY_RUN" != "true" ]]; then
  mkdir -p angevoice-adapter data/angevoice_prompts

  curl -fsSL "$REPO_RAW/adapters/angevoice.py" -o angevoice-adapter/angevoice.py
  curl -fsSL "$REPO_RAW/adapters/angevoice_stream.py" -o angevoice-adapter/angevoice_stream.py
  curl -fsSL "$REPO_RAW/adapters/angevoice_clone.py" -o angevoice-adapter/angevoice_clone.py
fi

log "适配器目录: $XIAOZHI_DIR/angevoice-adapter"

if [[ -n "$PROMPT_AUDIO" ]]; then
  if [[ ! -f "$PROMPT_AUDIO" ]]; then
    err "参考音频不存在: $PROMPT_AUDIO"
    exit 1
  fi

  if [[ "$DRY_RUN" != "true" ]]; then
    cp "$PROMPT_AUDIO" data/angevoice_prompts/reference.wav
  fi

  log "MOSS 克隆参考音频已复制到: data/angevoice_prompts/reference.wav"
fi

if [[ "$PATCH_COMPOSE" == "true" ]]; then
  patch_compose "$COMPOSE_FILE"
fi

if [[ "$WRITE_CONFIG" == "true" ]]; then
  if [[ "$DRY_RUN" != "true" ]]; then
    mkdir -p data
    [[ -f data/.config.yaml ]] || touch data/.config.yaml
  fi

  backup_file data/.config.yaml

  if [[ "$DRY_RUN" != "true" ]]; then
    sed -i '/# ===== AngeVoice Xiaozhi adapter begin =====/,/# ===== AngeVoice Xiaozhi adapter end =====/d' data/.config.yaml

    IFS='|' read -r selected type cfg_model voice fmt timeout prompt <<< "$(config_tuple)"
    write_config "$selected" "$type" "$cfg_model" "$voice" "$fmt" "$timeout" "$prompt"
  fi

  log "已写入 data/.config.yaml AngeVoice 示例配置"
fi

COMPOSE="$(compose_cmd)"

if [[ -n "$COMPOSE" && "$RESTART" == "true" && "$DRY_RUN" != "true" ]]; then
  log "重启小智 server 容器"

  if ! $COMPOSE -f "$COMPOSE_FILE" restart xiaozhi-esp32-server; then
    warn "重启失败，请手动执行: docker compose -f $COMPOSE_FILE restart xiaozhi-esp32-server"
  fi
fi

if command -v docker >/dev/null 2>&1 && [[ "$DRY_RUN" != "true" ]]; then
  if docker ps --format '{{.Names}}' | grep -q '^xiaozhi-esp32-server$'; then
    log "测试容器内适配器导入"

    docker exec xiaozhi-esp32-server python - <<'PY' || warn "适配器导入测试失败，请查看容器日志"
from core.providers.tts import angevoice, angevoice_stream, angevoice_clone
print("AngeVoice adapters import OK")
PY

    log "测试容器访问 AngeVoice /health"

    docker exec xiaozhi-esp32-server sh -lc "curl -fsS '${ANGEVOICE_HTTP}/health' >/dev/null" \
|| 警告容器访问 AngeVoice 失败，请确认 AngeVoice 已启动且 host.docker.internal 可用，或改用局域网 IP
  fi
fi

猫<<EOF

✅ AngeVoice 小智适配器安装流程完成

适配器目录：
  $XIAOZHI_DIR/angevoice-adapter

当前选择：
  mode=$MODE
  model=$MODEL
  http=$ANGEVOICE_HTTP
  ws=$ANGEVOICE_WS

MOSS 克隆参考音频：
  宿主机：$XIAOZHI_DIR/data/angevoice_prompts/reference.wav
  容器内：/opt/xiaozhi-esp32-server/data/angevoice_prompts/reference.wav

如果使用智控台：
  请到“语音合成 → 新增/创建副本”，按 xiaozhi/manager/presets.yaml 填入配置。
  智控台配置可能会覆盖 data/.config.yaml。

更换 MOSS 克隆声音：
  直接替换 reference.wav
  或把 prompt_audio_path 改成 /opt/xiaozhi-esp32-server/data/angevoice_prompts/你的音色.wav

EOF
