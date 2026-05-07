FROM nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /app

# Legacy GPU profile: conservative CUDA 11.8 runtime for older drivers/cards.
# ffmpeg is included for optional MP3 output when KOKORO_MP3_ENABLED=true.
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

# CUDA 11.8 PyTorch is usually more conservative than CUDA 12.x for older GPU environments.
# AngeVoice/MOSS 推理不需要 torchvision，保持镜像更轻。
RUN python3 -m pip install --no-cache-dir \
    "torch==${PYTORCH_VERSION}+cu118" \
    "torchaudio==${PYTORCH_VERSION}+cu118" \
    --index-url https://download.pytorch.org/whl/cu118

ARG INSTALL_MOSS=true
ARG MOSS_REPO=https://github.com/OpenMOSS/MOSS-TTS-Nano.git
ARG MOSS_RUNTIME_PACKAGE=onnxruntime-gpu==1.20.1
ARG MOSS_RUNTIME_INDEX_URL=https://aiinfra.pkgs.visualstudio.com/PublicPackages/_packaging/onnxruntime-cuda-11/pypi/simple/
ENV MOSS_TTS_NANO_PATH=/opt/MOSS-TTS-Nano
ENV LD_LIBRARY_PATH=/usr/local/cuda/lib64:/usr/local/nvidia/lib:/usr/local/nvidia/lib64:${LD_LIBRARY_PATH}

# MOSS-TTS-Nano ONNX runtime is preinstalled for legacy GPU images too, so users
# can opt into MOSS CUDA after validation without rebuilding the image. The
# Compose profile keeps that CUDA model hidden by default.
RUN if [ "$INSTALL_MOSS" = "true" ]; then \
      git clone --depth 1 "$MOSS_REPO" "$MOSS_TTS_NANO_PATH" && \
      python3 -m pip install --no-cache-dir "sentencepiece>=0.1.99" "huggingface_hub>=0.23" coloredlogs flatbuffers numpy packaging protobuf sympy && \
      python3 -m pip install --no-cache-dir --index-url "$MOSS_RUNTIME_INDEX_URL" "$MOSS_RUNTIME_PACKAGE"; \
    fi

COPY pyproject.toml README.md ./
COPY src/ src/

RUN python3 -m pip install --no-cache-dir -e .

# Preinstall spaCy English model used by Kokoro/Misaki to avoid runtime download.
RUN python3 -m pip install --no-cache-dir \
    en_core_web_sm@https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
