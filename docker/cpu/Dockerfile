FROM python:3.10-slim

WORKDIR /app

# 系统依赖
# ffmpeg 用于可选 MP3 转码；未开启 KOKORO_MP3_ENABLED 时不会影响默认路径
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    git \
    libsndfile1 \
    libgomp1 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

ARG INSTALL_MOSS=true
ARG MOSS_REPO=https://github.com/OpenMOSS/MOSS-TTS-Nano.git
ARG MOSS_RUNTIME_PACKAGE=onnxruntime>=1.20.0
ARG PYTORCH_VERSION=2.5.1
ENV MOSS_TTS_NANO_PATH=/opt/MOSS-TTS-Nano

# CPU 版 PyTorch。AngeVoice/MOSS 推理不需要 torchvision，保持镜像更轻。
RUN python3 -m pip install --no-cache-dir \
    "torch==${PYTORCH_VERSION}+cpu" \
    "torchaudio==${PYTORCH_VERSION}+cpu" \
    --index-url https://download.pytorch.org/whl/cpu

# MOSS-TTS-Nano CPU ONNX runtime. The official repository remains the source
# of inference code; AngeVoice only imports it through MOSS_TTS_NANO_PATH.
RUN if [ "$INSTALL_MOSS" = "true" ]; then \
      git clone --depth 1 "$MOSS_REPO" "$MOSS_TTS_NANO_PATH" && \
      python3 -m pip install --no-cache-dir "sentencepiece>=0.1.99" "huggingface_hub>=0.23" "$MOSS_RUNTIME_PACKAGE"; \
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

# 健康检查：每 30 秒访问 /health；ok/idle 都代表服务可用
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD python3 -c "import urllib.request, json; \
    d = json.loads(urllib.request.urlopen('http://localhost:8000/health').read()); \
    s = d.get('status', 'unknown'); \
    exit(0 if s in {'ok', 'idle'} else 1)" || exit 1

ENTRYPOINT ["/entrypoint.sh"]
