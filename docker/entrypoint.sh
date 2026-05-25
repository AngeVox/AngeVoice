#!/bin/bash
set -euo pipefail

# Compose profiles explicitly define provider/device settings for fnOS packages.
# ANGEVOICE_RUN_MODE remains an optional compatibility override for manual callers;
# when it is explicitly supplied, it must win over CPU-safe env-file defaults.
case "${ANGEVOICE_RUN_MODE:-}" in
  gpu)
    export ANGEVOICE_DEPLOYMENT_PROFILE="gpu"
    export KOKORO_DEVICE="cuda"
    export MOSS_EXECUTION_PROVIDER="cuda"
    export MOSS_CUDA_ENABLED="true"
    export ZIPVOICE_EXECUTION_PROVIDER="cuda"
    export ZIPVOICE_CUDA_ENABLED="true"
    ;;
  legacy-gpu)
    export ANGEVOICE_DEPLOYMENT_PROFILE="legacy-gpu"
    export KOKORO_DEVICE="cuda"
    export MOSS_EXECUTION_PROVIDER="cpu"
    export MOSS_CUDA_ENABLED="false"
    export ZIPVOICE_EXECUTION_PROVIDER="cpu"
    export ZIPVOICE_CUDA_ENABLED="false"
    ;;
  cpu)
    export ANGEVOICE_DEPLOYMENT_PROFILE="cpu"
    export KOKORO_DEVICE="cpu"
    export MOSS_EXECUTION_PROVIDER="cpu"
    export MOSS_CUDA_ENABLED="false"
    export ZIPVOICE_EXECUTION_PROVIDER="cpu"
    export ZIPVOICE_CUDA_ENABLED="false"
    ;;
  "")
    export ANGEVOICE_DEPLOYMENT_PROFILE="${ANGEVOICE_DEPLOYMENT_PROFILE:-cpu}"
    export KOKORO_DEVICE="${KOKORO_DEVICE:-cpu}"
    export MOSS_EXECUTION_PROVIDER="${MOSS_EXECUTION_PROVIDER:-cpu}"
    export MOSS_CUDA_ENABLED="${MOSS_CUDA_ENABLED:-false}"
    export ZIPVOICE_EXECUTION_PROVIDER="${ZIPVOICE_EXECUTION_PROVIDER:-cpu}"
    export ZIPVOICE_CUDA_ENABLED="${ZIPVOICE_CUDA_ENABLED:-false}"
    ;;
  *)
    echo "Unsupported ANGEVOICE_RUN_MODE=${ANGEVOICE_RUN_MODE}" >&2
    exit 2
    ;;
esac

# 统一模型目录：Compose 默认把宿主机 ./models 挂载到 /app/models。
export ANGEVOICE_MODELS_ROOT="${ANGEVOICE_MODELS_ROOT:-/app/models}"
export KOKORO_MODEL_DIR="${KOKORO_MODEL_DIR:-${ANGEVOICE_MODELS_ROOT}/models--hexgrad--Kokoro-82M-v1.1-zh}"
export MOSS_MODEL_DIR="${MOSS_MODEL_DIR:-${ANGEVOICE_MODELS_ROOT}/MOSS-TTS-Nano-100M-ONNX}"
export MOSS_AUDIO_TOKENIZER_MODEL_DIR="${MOSS_AUDIO_TOKENIZER_MODEL_DIR:-${ANGEVOICE_MODELS_ROOT}/MOSS-Audio-Tokenizer-Nano-ONNX}"
export HF_HUB_CACHE="${HF_HUB_CACHE:-${ANGEVOICE_MODELS_ROOT}}"
export HUGGINGFACE_HUB_CACHE="${HUGGINGFACE_HUB_CACHE:-${HF_HUB_CACHE}}"
export HF_HOME="${HF_HOME:-${ANGEVOICE_MODELS_ROOT}/.hf}"
export MODELSCOPE_CACHE="${MODELSCOPE_CACHE:-${ANGEVOICE_MODELS_ROOT}/modelscope-cache}"
export ANGEVOICE_CREDENTIALS_DIR="${ANGEVOICE_CREDENTIALS_DIR:-/app/credentials}"
export ANGEVOICE_ADMIN_CREDENTIALS_FILE="${ANGEVOICE_ADMIN_CREDENTIALS_FILE:-${ANGEVOICE_CREDENTIALS_DIR}/admin-credentials.json}"
export ANGEVOICE_API_KEY_FILE="${ANGEVOICE_API_KEY_FILE:-${ANGEVOICE_CREDENTIALS_DIR}/.angevoice-api-key}"
export ANGEVOICE_RUNTIME_CONFIG_FILE="${ANGEVOICE_RUNTIME_CONFIG_FILE:-/app/config/runtime-config.json}"

mkdir -p \
  "${KOKORO_MODEL_DIR}/voices" \
  "${MOSS_MODEL_DIR}" \
  "${MOSS_AUDIO_TOKENIZER_MODEL_DIR}" \
  "${HF_HOME}" \
  "${MODELSCOPE_CACHE}" \
  "${ANGEVOICE_OUTPUT_DIR:-/app/outputs}" \
  "${ANGEVOICE_CREDENTIALS_DIR}" \
  "$(dirname "${ANGEVOICE_RUNTIME_CONFIG_FILE}")" \
  "/app/logs"

exec angevoice serve
