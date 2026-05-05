FROM nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /app

# Legacy GPU profile: conservative CUDA 11.8 runtime for older drivers/cards.
# ffmpeg is included for optional MP3 output when KOKORO_MP3_ENABLED=true.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      python3.10 \
      python3.10-dev \
      python3.10-venv \
      python3-pip \
      libsndfile1 \
      ffmpeg \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.10 1 && \
    python3.10 -m pip install --upgrade pip

# CUDA 11.8 PyTorch is usually more conservative than CUDA 12.x for older GPU environments.
RUN python3 -m pip install --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

COPY pyproject.toml README.md ./
COPY src/ src/

RUN python3 -m pip install --no-cache-dir .

# Preinstall spaCy English model used by Kokoro/Misaki to avoid runtime download.
RUN python3 -m pip install --no-cache-dir \
    en_core_web_sm@https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
