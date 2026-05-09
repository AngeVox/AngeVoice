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

# GPU 版 PyTorch。AngeVoice/MOSS 推理不需要 torchvision，保持镜像更轻。
RUN python3 -m pip install --no-cache-dir \
    "torch==${PYTORCH_VERSION}+cu121" \
    "torchaudio==${PYTORCH_VERSION}+cu121" \
    --index-url https://download.pytorch.org/whl/cu121

ARG INSTALL_MOSS=true
ARG MOSS_REPO=https://github.com/OpenMOSS/MOSS-TTS-Nano.git
ARG MOSS_RUNTIME_PACKAGE=onnxruntime-gpu==1.20.2
ARG MOSS_CUDNN_PACKAGE=nvidia-cudnn-cu12==9.1.0.70
ENV MOSS_TTS_NANO_PATH=/opt/MOSS-TTS-Nano
ENV LD_LIBRARY_PATH=/usr/local/lib/python3.10/dist-packages/nvidia/cudnn/lib:/usr/local/lib/python3.10/dist-packages/nvidia/cublas/lib:/usr/local/cuda/lib64:/usr/local/nvidia/lib:/usr/local/nvidia/lib64:${LD_LIBRARY_PATH}

# MOSS-TTS-Nano ONNX runtime is included by default in the modern GPU image so
# the Web UI can switch between Kokoro, MOSS CPU, and MOSS CUDA without rebuilds.
# ONNX Runtime 1.20.x on CUDA 12 requires the cuDNN 9 runtime.
RUN if [ "$INSTALL_MOSS" = "true" ]; then \
      git clone --depth 1 "$MOSS_REPO" "$MOSS_TTS_NANO_PATH" && \
      python3 -m pip install --no-cache-dir "sentencepiece>=0.1.99" "huggingface_hub>=0.23" "$MOSS_RUNTIME_PACKAGE" "$MOSS_CUDNN_PACKAGE"; \
    fi

# 复制项目
COPY pyproject.toml README.md ./
COPY src/ src/

# 安装项目。使用 editable 模式让 Compose 挂载的模板/静态资源能立即生效。
RUN python3 -m pip install --no-cache-dir -e .

# 预装 spaCy 英文模型（misaki/kokoro 依赖，避免每次启动重新下载）
RUN python3 -m pip install --no-cache-dir \
    en_core_web_sm@https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000

# 健康检查：每 30 秒访问 /health，10 秒超时，启动后给 60 秒缓冲期
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD python3 -c "import urllib.request, json; \
    d = json.loads(urllib.request.urlopen('http://localhost:8000/health').read()); \
    s = d.get('status', 'unknown'); \
    exit(0 if s == 'ok' else 1)" || exit 1

ENTRYPOINT ["/entrypoint.sh"]
