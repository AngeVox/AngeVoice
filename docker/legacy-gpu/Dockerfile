FROM nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /app

# Legacy GPU 配置：使用 CUDA 11.8 运行时，兼容旧款驱动和显卡。
# ffmpeg 用于可选 MP3 输出（KOKORO_MP3_ENABLED=true 时生效）。
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      ca-certificates \
      git \
      python3.10 \
      python3.10-dev \
      python3.10-venv \
      python3-pip \
      libsndfile1 \
      libgomp1 \
      ffmpeg \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.10 1 && \
    python3.10 -m pip install --upgrade pip

ARG PYTORCH_VERSION=2.5.1

# CUDA 11.8 版 PyTorch 比 CUDA 12.x 更保守，适合旧 GPU 环境。
# AngeVoice/MOSS 推理不需要 torchvision，保持镜像更轻。
RUN python3 -m pip install --no-cache-dir \
    "torch==${PYTORCH_VERSION}+cu118" \
    "torchaudio==${PYTORCH_VERSION}+cu118" \
    --index-url https://download.pytorch.org/whl/cu118

ARG INSTALL_MOSS=true
ARG INSTALL_ZIPVOICE=true
ARG MOSS_REPO=https://github.com/OpenMOSS/MOSS-TTS-Nano.git
ARG MOSS_RUNTIME_PACKAGE=onnxruntime-gpu==1.20.1
ARG MOSS_RUNTIME_INDEX_URL=https://aiinfra.pkgs.visualstudio.com/PublicPackages/_packaging/onnxruntime-cuda-11/pypi/simple/
ENV MOSS_TTS_NANO_PATH=/opt/MOSS-TTS-Nano
ENV ZIPVOICE_REPO_PATH=/opt/ZipVoice
ENV LD_LIBRARY_PATH=/usr/local/cuda/lib64:/usr/local/nvidia/lib:/usr/local/nvidia/lib64:${LD_LIBRARY_PATH}

# MOSS-TTS-Nano ONNX 推理运行时也预装在 legacy GPU 镜像中，
# 用户可在验证后启用 MOSS CUDA 而无需重新构建镜像。
# Compose 配置默认隐藏该 CUDA 模型。
# 保留上游 OpenMOSS 许可证到预构建镜像中。
RUN if [ "$INSTALL_MOSS" = "true" ]; then \
      git clone --depth 1 "$MOSS_REPO" "$MOSS_TTS_NANO_PATH" && \
      mkdir -p /app/licenses && \
      if [ -f "$MOSS_TTS_NANO_PATH/LICENSE" ]; then cp "$MOSS_TTS_NANO_PATH/LICENSE" /app/licenses/MOSS-TTS-Nano-LICENSE; fi && \
      python3 -m pip install --no-cache-dir "sentencepiece>=0.1.99" "huggingface_hub>=0.23" "modelscope>=1.20.0" coloredlogs flatbuffers numpy packaging protobuf sympy && \
      python3 -m pip install --no-cache-dir --index-url "$MOSS_RUNTIME_INDEX_URL" "$MOSS_RUNTIME_PACKAGE"; \
    fi

COPY pyproject.toml README.md README_EN.md LICENSE THIRD_PARTY_NOTICES.md ACKNOWLEDGEMENTS.md ./
COPY licenses/ licenses/
COPY src/ src/
COPY scripts/ scripts/
COPY vendor/ZipVoice/ /opt/ZipVoice/

RUN python3 -m pip install --no-cache-dir -e .

# ZipVoice 使用已冻结的 ONNX INT8 CPU runtime。GPU 镜像复用 onnxruntime-gpu 的 CPUExecutionProvider，
# 不额外安装 onnxruntime CPU 包，避免覆盖 MOSS 的 CUDA runtime。
RUN if [ "$INSTALL_ZIPVOICE" = "true" ]; then \
      python3 -m pip install --no-cache-dir "huggingface_hub>=0.23" "lhotse>=1.24.0" "vocos>=0.1.0" "pydub>=0.25.1" "cn2an>=0.5.22" "inflect>=7.0.0" "piper_phonemize>=1.1.0" "safetensors>=0.4.0" "setuptools<81" && \
      mkdir -p /app/licenses && cp /opt/ZipVoice/LICENSE /app/licenses/ZipVoice-Apache-2.0-LICENSE && \
      python3 -c "import sys, onnxruntime as ort; assert 'CPUExecutionProvider' in ort.get_available_providers(); sys.path.insert(0, '/opt/ZipVoice'); from zipvoice.bin.infer_zipvoice_onnx import OnnxModel, generate_sentence; from zipvoice.tokenizer.tokenizer import EmiliaTokenizer; from zipvoice.utils.feature import VocosFbank; print('ZipVoice ONNX CPU provider import smoke check: OK')"; \
    fi

# 构建阶段验证已安装依赖元数据一致性，尽早发现运行时依赖冲突。
RUN python3 -m pip check

# 预装 spaCy 英文模型（misaki/kokoro 依赖，避免每次启动重新下载）
RUN python3 -m pip install --no-cache-dir \
    en_core_web_sm@https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl

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
