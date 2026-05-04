<div align="center">

# AngeVoice

**Lightweight Chinese TTS self-hosted service**  
Built on **Kokoro v1.1** model with OpenAI-compatible API, WebSocket streaming, Web UI, batch synthesis, and Docker deployment.

[![CI](https://github.com/ang77712829/AngeVoice/actions/workflows/ci.yml/badge.svg)](https://github.com/ang77712829/AngeVoice/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Docker](https://img.shields.io/badge/docker-cpu%20%7C%20gpu%20%7C%20legacy--gpu-2496ED.svg)](docker)

**🌐 Language / 语言**

**English** (current) | [**中文**](README.md)

</div>

---

## Introduction

AngeVoice is a Chinese TTS service project built and maintained by **安歌 (Ange)**. It is not a new model trained from scratch, but an engineering wrapper around the **Kokoro v1.1 Chinese model**, designed to simplify local deployment, API integration, web streaming playback, and Docker self-hosting.

Ideal use cases:

- Local / intranet Chinese speech synthesis service
- OpenAI-compatible TTS API backend
- Agent, reader, audiobook, dubbing tool integration
- NAS, home server, GPU / legacy graphics card deployment
- Web applications needing WebSocket per-segment playback and stop generation

> Model source: This project is built on [Kokoro v1.1 / Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) and its Chinese model. Model copyright, license, and restrictions follow the original model repository.

## Feature Highlights

- **OpenAI-compatible API** — `/v1/audio/speech` with `model/input/voice/speed/response_format`
- **Web UI** — Built-in AngeVoice frontend with voice selection, voice preview, streaming playback, and stop generation
- **WebSocket streaming** — Per-segment audio push, `cancel/stop` control, JSON/base64 and optional binary audio frames
- **Batch synthesis** — `/v1/audio/batch` returns ZIP, suitable for segment dubbing and audiobook workflows
- **Service features** — Request ID, `/stats`, `/requests`, timeout control, LRU cache, basic metrics
- **Text normalization** — Conservative Chinese TN for dates, money, percentages, phone numbers, and long IDs
- **Admin APIs** — Optional cache clearing, voice listing, `.pt` voice upload
- **MP3 output** — Optional MP3 behind `KOKORO_MP3_ENABLED=true` via ffmpeg
- **Docker** — CPU, GPU, and Legacy GPU Compose profiles with inline config comments
- **CLI** — `kokoro-tts serve / synth / voices` for headless and scripted use

## Quick Start

### Docker GPU

```bash
git clone https://github.com/ang77712829/AngeVoice.git
cd AngeVoice/docker/gpu
sudo docker compose up -d --build
```

Visit: `http://localhost:8101`

### Docker CPU / Legacy GPU

```bash
# Auto-select the fastest registry (same as above)
cd docker && bash select-registry.sh v2.4.0

# CPU, default port 8100
cd cpu && sudo docker compose up -d

# Legacy GPU, default port 8102, CUDA 11.8
cd ../legacy-gpu && sudo docker compose up -d
```

### pip install

```bash
git clone https://github.com/ang77712829/AngeVoice.git
cd AngeVoice
pip install -e .

kokoro-tts serve --port 8000
kokoro-tts synth "Hello world" -o hello.wav -v zm_010
kokoro-tts voices
```

## API Examples

### OpenAI-compatible TTS

```bash
curl -X POST http://localhost:8000/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"model":"kokoro","input":"Hello world","voice":"zm_010","response_format":"wav"}' \
  --output output.wav
```

Supported formats:

- `wav` — Default, most compatible
- `pcm` — Raw PCM s16le
- `mp3` — Requires `KOKORO_MP3_ENABLED=true` and ffmpeg

### WebSocket Streaming

```javascript
const ws = new WebSocket("ws://localhost:8000/ws/v1/tts");

ws.onopen = () => {
  ws.send(JSON.stringify({
    text: "Hello, this is streaming synthesis.",
    voice: "zm_010",
    speed: 1.0,
    format: "pcm_s16le",
    binary: false
  }));
};

ws.onmessage = (e) => {
  if (typeof e.data !== "string") return; // binary frame
  const msg = JSON.parse(e.data);
  if (msg.type === "audio") {
    playPCM(msg.data);
  }
};

// Cancel remaining segments
ws.send(JSON.stringify({ type: "cancel" }));
```

Message types: `started`, `audio`, `segment_error`, `done`, `cancelled`, `error`

<details>
<summary><strong>More API examples</strong></summary>

### Legacy API

```bash
curl -X POST http://localhost:8000/api/tts \
  -H "Content-Type: application/json" \
  -d '{"text":"Hello world","voice":"zm_010","format":"wav"}' \
  --output output.wav
```

### Batch Synthesis

```bash
curl -X POST http://localhost:8000/v1/audio/batch \
  -H "Content-Type: application/json" \
  -d '{"voice":"zm_010","speed":1.0,"response_format":"wav","items":[{"text":"First segment","filename":"001"},{"text":"Second segment","filename":"002"}]}' \
  --output batch.zip
```

ZIP contains audio files and `manifest.json`.

### Status Endpoints

```bash
curl http://localhost:8000/health
curl http://localhost:8000/stats
curl http://localhost:8000/requests
curl http://localhost:8000/v1/audio/formats
curl http://localhost:8000/v1/audio/voices
```

### Admin APIs

Disabled by default. Enable with API key:

```bash
KOKORO_ADMIN_ENABLED=true
KOKORO_API_KEY=change-me
```

```bash
curl -X DELETE http://localhost:8000/admin/cache \
  -H "Authorization: Bearer change-me"

curl http://localhost:8000/admin/voices \
  -H "Authorization: Bearer change-me"
```

Voice upload also requires:

```bash
KOKORO_VOICE_UPLOAD_ENABLED=true
```

For Docker deployments, mount the voices directory as writable:

```yaml
- ../../models/voices:/app/models/voices:rw
```

</details>

## Model Files

On first run, if no local model files are found, the service automatically downloads from Hugging Face. For offline deployment or faster cold start, prepare models manually.

<details>
<summary><strong>Manual model download</strong></summary>

```bash
pip install huggingface_hub
huggingface-cli download hexgrad/Kokoro-82M-v1.1-zh \
  --local-dir models/ \
  --include "config.json" "kokoro-v1_1-zh.pth" "voices/*.pt"
```

Required files:

```text
models/config.json
models/kokoro-v1_1-zh.pth
models/voices/*.pt
```

</details>

## Configuration

Common configuration is included in the three Docker Compose templates with inline comments. Full variable list:

<details>
<summary><strong>Environment variables</strong></summary>

| Variable | Default | Description |
|---|---|---|
| `KOKORO_MODEL_DIR` | `./models` | Model directory |
| `KOKORO_HOST` | `0.0.0.0` | Listen address |
| `KOKORO_PORT` | `8000` | Service port |
| `KOKORO_DEVICE` | `auto` | `auto` / `cpu` / `cuda` |
| `KOKORO_WORKERS` | `1` | Uvicorn workers; keep 1 for GPU |
| `KOKORO_MAX_CONCURRENT_REQUESTS` | `1` | Max in-process synthesis concurrency |
| `KOKORO_REQUEST_TIMEOUT_SECONDS` | `300` | Synthesis timeout |
| `KOKORO_MAX_TEXT_LENGTH` | `10000` | Max input text length |
| `KOKORO_SEGMENT_LENGTH` | `100` | Target segment length |
| `KOKORO_DEFAULT_VOICE` | `zm_010` | Default voice |
| `KOKORO_DEFAULT_SPEED` | `1.0` | Default speed |
| `KOKORO_STREAM_FORMAT` | `pcm_s16le` | Default WebSocket stream format |
| `KOKORO_STREAM_BINARY_ENABLED` | `true` | Enable binary WebSocket audio frames |
| `KOKORO_CACHE_ENABLED` | `true` | Enable LRU audio cache |
| `KOKORO_CACHE_MAX_ITEMS` | `128` | Cache item limit |
| `KOKORO_QUEUE_STATUS_ENABLED` | `true` | Enable `/requests` |
| `KOKORO_METRICS_ENABLED` | `true` | Enable `/stats` |
| `KOKORO_BATCH_ENABLED` | `true` | Enable batch synthesis |
| `KOKORO_BATCH_MAX_ITEMS` | `20` | Max batch items |
| `KOKORO_BATCH_CONCURRENCY` | `1` | Batch internal concurrency |
| `KOKORO_ADMIN_ENABLED` | `false` | Enable admin APIs |
| `KOKORO_VOICE_UPLOAD_ENABLED` | `false` | Enable `.pt` voice upload |
| `KOKORO_MP3_ENABLED` | `false` | Enable MP3 output |
| `KOKORO_MP3_BITRATE` | `192k` | MP3 bitrate (64k–320k) |
| `KOKORO_API_KEY` | - | Bearer API key |
| `KOKORO_CORS_ORIGINS` | `http://localhost:8000` | Comma-separated CORS origins |

</details>

## Testing & Benchmarking

```bash
pip install -e '.[dev]'
pytest -q
```

Service smoke test:

```bash
chmod +x scripts/smoke_test.sh scripts/loop_test.sh
BASE_URL=http://127.0.0.1:8101 ./scripts/smoke_test.sh
N=50 BASE_URL=http://127.0.0.1:8101 ./scripts/loop_test.sh
```

Streaming latency benchmark:

```bash
python scripts/benchmark_streaming.py \
  --angevoice-http http://127.0.0.1:8101 \
  --angevoice-ws ws://127.0.0.1:8101/ws/v1/tts
```

## Docker Images & Publishing

CI automatically pushes to three registries. Regular `main` pushes only verify builds; pushing a `v*` tag or manually triggering with `publish=true` publishes images.

Expected image names:

```text
ghcr.io/ang77712829/angevoice-cpu:v2.4.0
ghcr.io/ang77712829/angevoice-gpu:v2.4.0
ghcr.io/ang77712829/angevoice-legacy-gpu:v2.4.0
docker.io/maxblack777/angevoice-cpu:v2.4.0
docker.io/maxblack777/angevoice-gpu:v2.4.0
docker.io/maxblack777/angevoice-legacy-gpu:v2.4.0
cr.ccs.tencentyun.com/angeangeange/angevoice-cpu:v2.4.0
cr.ccs.tencentyun.com/angeangeange/angevoice-gpu:v2.4.0
cr.ccs.tencentyun.com/angeangeange/angevoice-legacy-gpu:v2.4.0
```



## Project Structure

<details>
<summary><strong>View directory tree</strong></summary>

```text
AngeVoice/
├── src/kokoro_tts/       # Core package
│   ├── config.py         # Configuration
│   ├── engine.py         # TTS engine & text normalization
│   ├── server.py         # FastAPI service
│   ├── service_extras.py # Batch/admin/MP3 extensions
│   ├── cli.py            # CLI tool
│   └── templates/        # Web UI
├── scripts/              # Smoke/stability/benchmark scripts
├── tests/                # Unit tests
├── docker/               # CPU/GPU/Legacy GPU Docker configs
├── docs/                 # Profiles, roadmap, release guide
├── models/               # Model files directory
├── pyproject.toml
├── README.md
└── README_EN.md
```

</details>

## Documentation

- [Service Profiles](docs/SERVICE_PROFILES.md)
- [v2.4 Features](docs/V2_4_FEATURES.md)
- [Legacy GPU Deployment](docker/legacy-gpu/README.md)
- [Roadmap](docs/ROADMAP.md)


## Changelog

<details>
<summary><strong>v2.4.0</strong></summary>

### Added

- AngeVoice Web UI with voice preview, streaming playback, and stop generation
- `/v1/audio/batch` batch ZIP synthesis with `manifest.json`
- `/v1/audio/formats` runtime format query
- Admin APIs: `/admin/cache`, `/admin/voices`, `/admin/voices/upload`
- Optional MP3 output behind `KOKORO_MP3_ENABLED=true`
- WebSocket `cancel` / `stop` control frames
- Basic Chinese text normalization: phone numbers, dates, money, percentages, long IDs
- CI, GHCR build workflow, and benchmark script
- Three standardized Docker profiles: CPU, GPU, Legacy GPU

### Improved

- FastAPI and package version synced to `2.4.0`
- Docker service names unified to `angevoice-*`
- CLI keeps `kokoro-tts` for backward compatibility
- `/health` returns batch/admin/mp3 status
- WebSocket cancel with backpressure queue
- Upload size limit and MP3 bitrate whitelist validation
- Test coverage updated, CI enabled for Python 3.10/3.11/3.12

</details>

<details>
<summary><strong>Earlier versions</strong></summary>

### v2.3.0

- `/stats`, `/requests`, request IDs, request status tracking, service metrics
- In-memory LRU audio cache
- Optional binary WebSocket audio frames
- Request timeout control
- General and conservative deployment profiles

### v2.1.x

- Audio format, concurrency, text segmentation, PCM encoding, and Docker startup fixes
- WebSocket per-segment streaming synthesis
- Model auto-download and offline download docs

### v1.0

- Initial Chinese synthesis, OpenAI-style API, Docker CPU/GPU deployment

</details>

## Acknowledgements

- [Kokoro v1.1 Model](https://huggingface.co/hexgrad/Kokoro-82M) — hexgrad
- [Kokoro Chinese Model](https://huggingface.co/hexgrad/Kokoro-82M-v1.1-zh) — hexgrad
- Original model license follows the model repository

## License

MIT