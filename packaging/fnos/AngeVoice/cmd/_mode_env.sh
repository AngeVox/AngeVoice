#!/bin/bash
# fnOS 单一 Docker 服务的模式变量写入器。
# 只更新 app/docker/.env；不得复制/替换 docker-compose.yaml，也不得在回调里启停容器。
set -eu

angevoice_write_mode_env() {
  local mode="${1:-cpu}"
  local env_path="${TRIM_APPDEST}/docker/.env"
  local image runtime profile device moss_provider moss_cuda zip_provider zip_cuda visible
  case "$mode" in
    cpu)
      image="ghcr.io/ang77712829/angevoice-cpu:latest"
      runtime="runc"; profile="cpu"; device="cpu"; moss_provider="cpu"; moss_cuda="false"; zip_provider="cpu"; zip_cuda="false"; visible="void"
      ;;
    gpu)
      image="ghcr.io/ang77712829/angevoice-gpu:latest"
      runtime="nvidia"; profile="gpu"; device="cuda"; moss_provider="cuda"; moss_cuda="true"; zip_provider="cuda"; zip_cuda="true"; visible="all"
      ;;
    legacy-gpu)
      image="ghcr.io/ang77712829/angevoice-legacy-gpu:latest"
      runtime="nvidia"; profile="legacy-gpu"; device="cuda"; moss_provider="cpu"; moss_cuda="false"; zip_provider="cpu"; zip_cuda="false"; visible="all"
      ;;
    *)
      echo "[AngeVoice] 运行模式无效：$mode" >&2
      return 1
      ;;
  esac
  mkdir -p "$(dirname "$env_path")"
  cat > "$env_path" <<EOF
# 由 AngeVoice fnOS 安装/设置向导维护；不含管理员密码或 API Key。
ANGEVOICE_FNOS_RUN_MODE=$mode
ANGEVOICE_FNOS_IMAGE=$image
ANGEVOICE_FNOS_RUNTIME=$runtime
ANGEVOICE_FNOS_PROFILE=$profile
ANGEVOICE_FNOS_KOKORO_DEVICE=$device
ANGEVOICE_FNOS_MOSS_PROVIDER=$moss_provider
ANGEVOICE_FNOS_MOSS_CUDA_ENABLED=$moss_cuda
ANGEVOICE_FNOS_ZIPVOICE_PROVIDER=$zip_provider
ANGEVOICE_FNOS_ZIPVOICE_CUDA_ENABLED=$zip_cuda
ANGEVOICE_FNOS_NVIDIA_VISIBLE_DEVICES=$visible
EOF
}
