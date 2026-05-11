#!/usr/bin/env bash
set -euo pipefail

REPO_RAW="https://raw.githubusercontent.com/ang77712829/AngeVoice/main/xiaozhi"
XIAOZHI_DIR=""
ANGEVOICE_HTTP="http://host.docker.internal:8101"
ANGEVOICE_WS="ws://host.docker.internal:8101/ws/v1/tts"
MODE="kokoro-stream"
API_KEY=""
PROMPT_AUDIO=""
WRITE_CONFIG="true"
PATCH_COMPOSE="true"
RESTART="true"
DRY_RUN="false"

log() { printf '\033[1;32m[AngeVoice-xiaozhi]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[WARN]\033[0m %s\n' "$*"; }
err() { printf '\033[1;31m[ERROR]\033[0m %s\n' "$*" >&2; }

usage() {
  cat <<'USAGE'
AngeVoice 小智后端适配器一键安装脚本

用法：
  bash <(curl -fsSL https://raw.githubusercontent.com/ang77712829/AngeVoice/main/xiaozhi/scripts/install-xiaozhi-adapter.sh)

常用参数：
  --xiaozhi-dir DIR       小智 docker-compose_all.yml 所在目录，默认自动探测/当前目录
  --angevoice-url URL     AngeVoice HTTP 地址，默认 http://host.docker.internal:8101
  --angevoice-ws URL      AngeVoice WS 地址，默认 ws://host.docker.internal:8101/ws/v1/tts
  --mode MODE             kokoro|kokoro-stream|moss|moss-stream|moss-clone|moss-clone-stream
  --api-key KEY           AngeVoice API Key，未启用鉴权可留空
  --prompt-audio FILE     MOSS 克隆参考音频，脚本会复制为 data/angevoice_prompts/reference.wav
  --no-config             不写入 data/.config.yaml，只安装适配器和 patch compose
  --no-compose            不修改 docker-compose_all.yml
  --no-restart            不重启 xiaozhi-esp32-server 容器
  --dry-run               只显示将要执行的操作
  -h, --help              显示帮助

推荐：
  Kokoro 流式：        --mode kokoro-stream
  MOSS 预设音色流式： --mode moss-stream
  MOSS 克隆流式：     --mode moss-clone-stream --prompt-audio ./reference.wav
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --xiaozhi-dir) XIAOZHI_DIR="$2"; shift 2 ;;
    --angevoice-url) ANGEVOICE_HTTP="${2%/}"; shift 2 ;;
    --angevoice-ws) ANGEVOICE_WS="$2"; shift 2 ;;
    --mode) MODE="$2"; shift 2 ;;
    --api-key) API_KEY="$2"; shift 2 ;;
    --prompt-audio) PROMPT_AUDIO="$2"; shift 2 ;;
    --no-config) WRITE_CONFIG="false"; shift ;;
    --no-compose) PATCH_COMPOSE="false"; shift ;;
    --no-restart) RESTART="false"; shift ;;
    --dry-run) DRY_RUN="true"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) err "未知参数: $1"; usage; exit 1 ;;
  esac
done

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    err "缺少命令: $1"
    exit 1
  fi
}

need_cmd curl
need_cmd sed
need_cmd python3

find_xiaozhi_dir() {
  if [[ -n "$XIAOZHI_DIR" ]]; then
    echo "$XIAOZHI_DIR"
    return
  fi
  if [[ -f "docker-compose_all.yml" && -d "data" ]]; then
    pwd
    return
  fi
  for d in "$HOME/xiaozhi-server" "/opt/xiaozhi-server" "/root/xiaozhi-server"; do
    if [[ -f "$d/docker-compose_all.yml" && -d "$d/data" ]]; then
      echo "$d"
      return
    fi
  done
  err "未找到小智目录。请在 xiaozhi-server 目录运行，或传入 --xiaozhi-dir /path/to/xiaozhi-server"
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

backup_file() {
  local file="$1"
  if [[ -f "$file" ]]; then
    local bak="${file}.angevoice.$(date +%Y%m%d-%H%M%S).bak"
    if [[ "$DRY_RUN" == "true" ]]; then
      log "[dry-run] 将备份: $bak"
    else
      cp "$file" "$bak"
      log "已备份: $bak"
    fi
  fi
}

XIAOZHI_DIR="$(find_xiaozhi_dir)"
cd "$XIAOZHI_DIR"

case "$MODE" in
  kokoro|kokoro-stream|moss|moss-stream|moss-clone|moss-clone-stream) ;;
  *) err "不支持的 mode: $MODE"; exit 1 ;;
esac

log "小智目录: $XIAOZHI_DIR"
log "AngeVoice HTTP: $ANGEVOICE_HTTP"
log "AngeVoice WS: $ANGEVOICE_WS"
log "安装模式: $MODE"

if [[ "$DRY_RUN" != "true" ]]; then
  mkdir -p angevoice-adapter data/angevoice_prompts
  curl -fsSL "$REPO_RAW/adapters/angevoice.py" -o angevoice-adapter/angevoice.py
  curl -fsSL "$REPO_RAW/adapters/angevoice_stream.py" -o angevoice-adapter/angevoice_stream.py
  curl -fsSL "$REPO_RAW/adapters/angevoice_clone.py" -o angevoice-adapter/angevoice_clone.py
fi
log "适配器已安装到: $XIAOZHI_DIR/angevoice-adapter"

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
  if [[ ! -f docker-compose_all.yml ]]; then
    err "未找到 docker-compose_all.yml"
    exit 1
  fi
  backup_file docker-compose_all.yml
  if ! grep -q "angevoice-adapter/angevoice.py" docker-compose_all.yml; then
    if [[ "$DRY_RUN" != "true" ]]; then
      python3 - <<'PY'
from pathlib import Path
path = Path('docker-compose_all.yml')
text = path.read_text(encoding='utf-8')
marker = '      - ./models/SenseVoiceSmall/model.pt:/opt/xiaozhi-esp32-server/models/SenseVoiceSmall/model.pt\n'
insert = '''      # AngeVoice TTS adapters\n      - ./angevoice-adapter/angevoice.py:/opt/xiaozhi-esp32-server/core/providers/tts/angevoice.py:ro\n      - ./angevoice-adapter/angevoice_stream.py:/opt/xiaozhi-esp32-server/core/providers/tts/angevoice_stream.py:ro\n      - ./angevoice-adapter/angevoice_clone.py:/opt/xiaozhi-esp32-server/core/providers/tts/angevoice_clone.py:ro\n      # MOSS clone prompt audio directory\n      - ./data/angevoice_prompts:/opt/xiaozhi-esp32-server/data/angevoice_prompts:ro\n'''
if marker in text:
    text = text.replace(marker, marker + insert, 1)
else:
    raise SystemExit('无法定位 volumes 挂载位置，请手动参考 xiaozhi/examples/docker-compose.patch.example.yml')
if 'host.docker.internal:host-gateway' not in text:
    anchor = '    security_opt:\n      - seccomp:unconfined\n'
    extra = '    extra_hosts:\n      - "host.docker.internal:host-gateway"\n'
    if anchor in text:
        text = text.replace(anchor, extra + anchor, 1)
    else:
        text = text.replace('    networks:\n      - default\n', '    networks:\n      - default\n' + extra, 1)
path.write_text(text, encoding='utf-8')
PY
    fi
    if [[ "$DRY_RUN" == "true" ]]; then
      log "[dry-run] 将 patch docker-compose_all.yml"
    else
      log "已 patch docker-compose_all.yml"
    fi
  else
    log "docker-compose_all.yml 已包含 AngeVoice 挂载，跳过 patch"
  fi
fi

write_config() {
  local selected="$1" type="$2" model="$3" voice="$4" fmt="$5" timeout="$6" prompt="$7"
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
    format: ${fmt}
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

if [[ "$WRITE_CONFIG" == "true" ]]; then
  if [[ "$DRY_RUN" != "true" ]]; then
    [[ -f data/.config.yaml ]] || touch data/.config.yaml
  fi
  backup_file data/.config.yaml
  if [[ "$DRY_RUN" != "true" ]]; then
    sed -i '/# ===== AngeVoice Xiaozhi adapter begin =====/,/# ===== AngeVoice Xiaozhi adapter end =====/d' data/.config.yaml
    case "$MODE" in
      kokoro) write_config "AngeVoiceKokoro" "angevoice" "kokoro" "zm_010" "wav" "120" "" ;;
      kokoro-stream) write_config "AngeVoiceKokoroStream" "angevoice_stream" "kokoro" "zm_010" "pcm_s16le" "180" "" ;;
      moss) write_config "AngeVoiceMoss" "angevoice" "moss-nano-cpu" "Junhao" "wav" "180" "" ;;
      moss-stream) write_config "AngeVoiceMossStream" "angevoice_stream" "moss-nano-cpu" "Junhao" "pcm_s16le" "240" "" ;;
      moss-clone) write_config "AngeVoiceMossClone" "angevoice_clone" "moss-nano-cpu" "Junhao" "wav" "300" "prompt" ;;
      moss-clone-stream) write_config "AngeVoiceMossCloneStream" "angevoice_stream" "moss-nano-cpu" "Junhao" "pcm_s16le" "300" "prompt" ;;
    esac
  fi
  if [[ "$DRY_RUN" == "true" ]]; then
    log "[dry-run] 将写入 data/.config.yaml AngeVoice 示例配置"
  else
    log "已写入 data/.config.yaml AngeVoice 示例配置"
  fi
fi

COMPOSE="$(compose_cmd)"
if [[ -n "$COMPOSE" && "$RESTART" == "true" && "$DRY_RUN" != "true" ]]; then
  log "重启小智 server 容器"
  $COMPOSE -f docker-compose_all.yml restart xiaozhi-esp32-server || warn "重启失败，请手动执行: docker compose -f docker-compose_all.yml restart xiaozhi-esp32-server"
fi

if command -v docker >/dev/null 2>&1 && [[ "$DRY_RUN" != "true" ]]; then
  if docker ps --format '{{.Names}}' | grep -q '^xiaozhi-esp32-server$'; then
    log "测试容器内适配器导入"
    docker exec xiaozhi-esp32-server python - <<'PY' || warn "适配器导入测试失败，请查看容器日志"
from core.providers.tts import angevoice, angevoice_stream, angevoice_clone
print('AngeVoice adapters import OK')
PY
    log "测试容器访问 AngeVoice /health"
    docker exec xiaozhi-esp32-server sh -lc "curl -fsS '${ANGEVOICE_HTTP}/health' >/dev/null" || warn "容器访问 AngeVoice 失败，请确认 AngeVoice 已启动且 host.docker.internal 可用"
  fi
fi

cat <<EOF

✅ AngeVoice 小智适配器安装完成

适配器目录：
  $XIAOZHI_DIR/angevoice-adapter

MOSS 克隆参考音频目录：
  宿主机：$XIAOZHI_DIR/data/angevoice_prompts/reference.wav
  容器内：/opt/xiaozhi-esp32-server/data/angevoice_prompts/reference.wav

如使用智控台：
  请到“语音合成 → 新增/创建副本”，按 xiaozhi/manager/presets.yaml 填入配置。
  智控台配置可能会覆盖 data/.config.yaml。

更换 MOSS 克隆声音：
  直接替换宿主机文件：$XIAOZHI_DIR/data/angevoice_prompts/reference.wav
  建议 3-10 秒清晰人声，wav/mp3 均可，但统一命名为 reference.wav 最省心。

EOF
