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
ARG INSTALL_ZIPVOICE=true
ENV MOSS_TTS_NANO_PATH=/opt/MOSS-TTS-Nano
ENV ZIPVOICE_REPO_PATH=/opt/ZipVoice

# CPU 版 PyTorch。AngeVoice/MOSS 推理不需要 torchvision，保持镜像更轻。
RUN python3 -m pip install --no-cache-dir \
    "torch==${PYTORCH_VERSION}+cpu" \
    "torchaudio==${PYTORCH_VERSION}+cpu" \
    --index-url https://download.pytorch.org/whl/cpu

# MOSS-TTS-Nano CPU ONNX 推理运行时。MOSS-TTS-Nano 官方仓库是推理代码来源，
# AngeVoice 通过 MOSS_TTS_NANO_PATH 环境变量引用它。
# 保留上游 OpenMOSS 许可证到预构建镜像中。
RUN if [ "$INSTALL_MOSS" = "true" ]; then \
      git clone --depth 1 "$MOSS_REPO" "$MOSS_TTS_NANO_PATH" && \
      mkdir -p /app/licenses && \
      if [ -f "$MOSS_TTS_NANO_PATH/LICENSE" ]; then cp "$MOSS_TTS_NANO_PATH/LICENSE" /app/licenses/MOSS-TTS-Nano-LICENSE; fi && \
      python3 -m pip install --no-cache-dir "sentencepiece>=0.1.99" "huggingface_hub>=0.23" "modelscope>=1.20.0" "$MOSS_RUNTIME_PACKAGE"; \
    fi

# 复制项目
COPY pyproject.toml README.md README_EN.md LICENSE THIRD_PARTY_NOTICES.md ACKNOWLEDGEMENTS.md ./
COPY licenses/ licenses/
COPY src/ src/
COPY scripts/ scripts/
COPY vendor/ZipVoice/ /opt/ZipVoice/

# 安装项目。使用 editable 模式让 Compose 挂载的模板/静态资源能立即生效。
RUN if [ "$INSTALL_ZIPVOICE" = "true" ]; then \
      python3 -m pip install --no-cache-dir -e ".[zipvoice]" && \
      mkdir -p /app/licenses && cp /opt/ZipVoice/LICENSE /app/licenses/ZipVoice-Apache-2.0-LICENSE; \
    else \
      python3 -m pip install --no-cache-dir -e .; \
    fi

# 构建阶段即验证 ZipVoice ONNX CPU 推理导入链，避免到 NAS 首次合成时才暴露遗漏依赖。
# 此检查不下载权重、不加载模型，也不会将权重固化进镜像。
RUN if [ "$INSTALL_ZIPVOICE" = "true" ]; then \
      python3 -c "import sys; sys.path.insert(0, '/opt/ZipVoice'); from zipvoice.bin.infer_zipvoice_onnx import OnnxModel, generate_sentence; from zipvoice.tokenizer.tokenizer import EmiliaTokenizer; from zipvoice.utils.feature import VocosFbank; print('ZipVoice ONNX CPU import smoke check: OK')"; \
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
