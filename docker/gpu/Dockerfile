FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# 安装 Python 3.10 + 系统依赖
# ffmpeg 用于可选 MP3 转码；未开启 KOKORO_MP3_ENABLED 时不会影响默认路径
# 使用 --no-install-recommends 减少依赖，并加重试逻辑应对网络抖动
RUN for i in 1 2 3; do \
      apt-get update && break || sleep 5; \
    done && \
    apt-get install -y --no-install-recommends \
      ca-certificates \
      git \
      python3.10 \
      python3.10-dev \
      python3.10-venv \
      python3-pip \
      libsndfile1 \
      libgomp1 \
      ffmpeg && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# 确保 python3 和 pip3 都指向 3.10
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.10 1 && \
    python3.10 -m pip install --upgrade pip

ARG PYTORCH_VERSION=2.5.1

# 依赖约束先复制到镜像中，后续 pip install 全部使用同一份约束，避免 transformers 等间接依赖漂移。
COPY docker/constraints-gpu.lock /app/docker/constraints-gpu.lock

# GPU 版 PyTorch。AngeVoice/MOSS 推理不需要 torchvision，保持镜像更轻。
# 注意：不使用 -c constraints-gpu.lock，因为 CUDA index 无法解析其中的非 torch 依赖。
RUN python3 -m pip install --no-cache-dir \
    "torch==${PYTORCH_VERSION}+cu121" \
    "torchaudio==${PYTORCH_VERSION}+cu121" \
    --index-url https://download.pytorch.org/whl/cu121

ARG INSTALL_MOSS=true
ARG INSTALL_ZIPVOICE=true
ARG MOSS_REPO=https://github.com/OpenMOSS/MOSS-TTS-Nano.git
ARG MOSS_REF=b09d1962a7df4d4007146ea53880c4b282d83e39
ARG MOSS_RUNTIME_PACKAGE=onnxruntime-gpu==1.20.2
ARG MOSS_CUDNN_PACKAGE=nvidia-cudnn-cu12==9.1.0.70
ENV MOSS_TTS_NANO_PATH=/opt/MOSS-TTS-Nano
ENV ZIPVOICE_REPO_PATH=/opt/ZipVoice
ENV LD_LIBRARY_PATH=/usr/local/lib/python3.10/dist-packages/nvidia/cudnn/lib:/usr/local/lib/python3.10/dist-packages/nvidia/cublas/lib:/usr/local/cuda/lib64:/usr/local/nvidia/lib:/usr/local/nvidia/lib64:${LD_LIBRARY_PATH}

# MOSS-TTS-Nano ONNX 推理运行时已预装在 GPU 镜像中，Web UI 可在
# Kokoro、MOSS CPU、MOSS CUDA 之间切换而无需重新构建。
# ONNX Runtime 1.20.x 在 CUDA 12 上需要 cuDNN 9 运行时。
# 保留上游 OpenMOSS 许可证到预构建镜像中。
RUN if [ "$INSTALL_MOSS" = "true" ]; then \
      mkdir -p "$MOSS_TTS_NANO_PATH" && \
      git init "$MOSS_TTS_NANO_PATH" && \
      cd "$MOSS_TTS_NANO_PATH" && git remote add origin "$MOSS_REPO" && \
      (git fetch --depth 1 origin "$MOSS_REF" || git fetch --depth 1 origin main) && \
      git checkout --detach "$MOSS_REF" && \
      rm -rf .git && cd /app && \
      mkdir -p /app/licenses && \
      if [ -f "$MOSS_TTS_NANO_PATH/LICENSE" ]; then cp "$MOSS_TTS_NANO_PATH/LICENSE" /app/licenses/MOSS-TTS-Nano-LICENSE; fi && \
      python3 -m pip install --no-cache-dir -c /app/docker/constraints-gpu.lock sentencepiece huggingface_hub modelscope "$MOSS_RUNTIME_PACKAGE" "$MOSS_CUDNN_PACKAGE" && \
      python3 -c "import sys; sys.path.insert(0, '$MOSS_TTS_NANO_PATH'); import onnx_tts_runtime; print('MOSS ONNX runtime import smoke check: OK')"; \
    fi

# 复制项目
COPY pyproject.toml README.md README_EN.md LICENSE NOTICE THIRD_PARTY_NOTICES.md ACKNOWLEDGEMENTS.md ./
COPY licenses/ licenses/
COPY src/ src/
COPY scripts/ scripts/
COPY vendor/ZipVoice/ /opt/ZipVoice/

# 安装项目。使用 editable 模式让 Compose 挂载的模板/静态资源能立即生效。
RUN python3 -m pip install --no-cache-dir -c /app/docker/constraints-gpu.lock -e .

# ZipVoice 在标准 GPU 镜像中支持 PyTorch CUDA runtime，同时保留已冻结的 ONNX INT8 CPU fallback。
# 仍复用 onnxruntime-gpu 的 CPUExecutionProvider，不额外安装 onnxruntime CPU 包，避免覆盖 MOSS CUDA runtime。
RUN if [ "$INSTALL_ZIPVOICE" = "true" ]; then \
      python3 -m pip install --no-cache-dir -c /app/docker/constraints-gpu.lock huggingface_hub lhotse vocos pydub cn2an inflect piper_phonemize safetensors "setuptools<81" && \
      mkdir -p /app/licenses && cp /opt/ZipVoice/LICENSE /app/licenses/ZipVoice-Apache-2.0-LICENSE && \
      python3 -c "import sys, onnxruntime as ort; assert 'CPUExecutionProvider' in ort.get_available_providers(); sys.path.insert(0, '/opt/ZipVoice'); from zipvoice.bin.infer_zipvoice_onnx import OnnxModel, generate_sentence; from zipvoice.tokenizer.tokenizer import EmiliaTokenizer; from zipvoice.utils.feature import VocosFbank; from kokoro_tts.zipvoice.runtime_cuda_torch import ZipVoiceTorchCudaRuntime; print('ZipVoice CUDA adapter + ONNX CPU fallback import smoke check: OK')"; \
    fi

# 构建阶段验证已安装依赖元数据一致性，尽早发现运行时依赖冲突。
RUN python3 -m pip check

# 预装 spaCy 英文模型（misaki/kokoro 依赖，避免每次启动重新下载）
RUN python3 -m pip install --no-cache-dir \
    en_core_web_sm@https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl

# 构建阶段验证 Kokoro import 链，避免 transformers/torch 版本组合漂移到运行时才失败。
RUN python3 -c "import torch, transformers; from kokoro import KModel, KPipeline; print('Kokoro import smoke check: OK'); print('torch:', torch.__version__); print('transformers:', transformers.__version__)"

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000

# 健康检查：每 30 秒访问 /health；ok/idle 都代表服务可用
HEALTHCHECK --interval=30s --timeout=10s --start-period=300s --retries=3 \
  CMD python3 -c "import urllib.request, json; \
    d = json.loads(urllib.request.urlopen('http://localhost:8000/health').read()); \
    s = d.get('status', 'unknown'); \
    exit(0 if s in {'ok', 'idle'} else 1)" || exit 1

ENTRYPOINT ["/entrypoint.sh"]
