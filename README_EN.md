# AngeVoice

> Lightweight Chinese TTS self-hosted service. AngeVoice wraps the Kokoro v1.1 Chinese model with OpenAI-compatible APIs, WebSocket segment streaming, Web UI, batch synthesis, cache, metrics, and CPU/GPU/legacy-GPU Docker profiles.

English | [中文](README.md)

[![CI](https://github.com/ang77712829/AngeVoice/actions/workflows/ci.yml/badge.svg)](https://github.com/ang77712829/AngeVoice/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

## What is AngeVoice?

AngeVoice is not a newly trained model. It is a service-oriented wrapper around the Kokoro v1.1 Chinese model, designed to make local deployment, intranet usage, OpenAI-style integration, browser streaming playback, and Docker self-hosting easier.

Good fits:

- Local/NAS/home-server Chinese speech synthesis
- TTS backend for agents, readers, audiobooks, and dubbing tools
- OpenAI-compatible TTS API backend
- Web apps that need segment playback, stop generation, and batch ZIP export
- CPU, NVIDIA GPU, and legacy/conservative CUDA environments

> Model source: this project is built on Kokoro v1.1 / Kokoro-82M and its Chinese model. Model copyright, license, and restrictions follow the upstream model repositories.

## Highlights

| Capability | Description |
|---|---|
| OpenAI-compatible API | `POST /v1/audio/speech` with `model/input/voice/speed/response_format` |
| Web UI | Built-in page with voice selection, preview, streaming playback, and stop generation |
| WebSocket streaming | `ws://.../ws/v1/tts` segment streaming with `cancel` / `stop` control frames |
| Batch synthesis | `POST /v1/audio/batch` returns a ZIP and `manifest.json` |
| Service controls | Request IDs, `/health`, `/stats`, `/requests`, timeout, concurrency guard, LRU cache |
| Admin APIs | Optional cache clearing, voice listing, and `.pt` voice upload |
| Output formats | WAV, PCM s16le, optional MP3 through ffmpeg |
| Docker | CPU, GPU, and Legacy GPU Compose profiles |
| CLI | Recommended command: `angevoice`; legacy `kokoro-tts` remains supported |

## v2.5 modular refactor

v2.5 splits the previously heavy `server.py` into focused modules while keeping the public entry points compatible:

```text
src/kokoro_tts/
├── server.py             # FastAPI app assembly: create_app / run_server
├── service_state.py      # Runtime state, cache, metrics, concurrency, synthesis dispatch
├── security.py           # HTTP / WebSocket API-key checks
├── api_models.py         # Pydantic request models
├── routes/
│   ├── status.py         # /, /health, /stats, /requests, voices, cancel
│   ├── audio.py          # /v1/audio/speech and /api/tts
│   └── ws.py             # /ws/v1/tts
├── service_extras.py     # batch/admin/mp3 extension routes
├── engine.py             # Kokoro engine, segmentation, normalization, audio encoding
└── config.py             # configuration and environment variables
```

Compatibility notes:

- The Python import package remains `kokoro_tts` to avoid breaking existing users.
- The distribution/project name is now `angevoice`.
- The new CLI is `angevoice`; the historical `kokoro-tts` command remains as an alias.
- Kokoro model loading does not depend on the distribution package name. It depends on the upstream `kokoro` package, model directory, model filenames, and Hugging Face repo.

## Quick start

### Docker GPU

```bash
git clone https://github.com/ang77712829/AngeVoice.git
cd AngeVoice/docker/gpu
sudo docker compose up -d
```

Default URL: `http://localhost:8101`

```bash
curl http://127.0.0.1:8101/health
curl http://127.0.0.1:8101/stats
```

### Docker CPU / Legacy GPU

```bash
# CPU, default port 8100
cd docker/cpu && sudo docker compose up -d

# Legacy GPU, default port 8102, CUDA 11.8
cd docker/legacy-gpu && sudo docker compose up -d
```

Build locally if needed:

```bash
sudo docker compose up -d --build
```

### Editable pip install

```bash
git clone https://github.com/ang77712829/AngeVoice.git
cd AngeVoice
pip install -e .

angevoice serve --port 8000
angevoice synth "Hello world" -o hello.wav -v zm_010
angevoice voices

# Legacy command still works
kokoro-tts serve --port 8000
```

## API examples

### OpenAI-compatible TTS

```bash
curl -X POST http://localhost:8000/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"model":"kokoro","input":"Hello world","voice":"zm_010","response_format":"wav"}' \
  --output output.wav
```

Supported formats: `wav`, `pcm`, `mp3`. MP3 requires `KOKORO_MP3_ENABLED=true` and ffmpeg.

### WebSocket streaming

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

ws.send(JSON.stringify({ type: "cancel" }));
```

Message types: `started`, `audio`, `segment_error`, `done`, `cancelled`, `error`.

### Batch ZIP synthesis

```bash
curl -X POST http://localhost:8000/v1/audio/batch \
  -H "Content-Type: application/json" \
  -d '{"voice":"zm_010","speed":1.0,"response_format":"wav","items":[{"text":"First segment","filename":"001"},{"text":"Second segment","filename":"002"}]}' \
  --output batch.zip
```

## Model files

If local model files are not found, the service falls back to Hugging Face download. For offline deployments or faster cold starts, prepare the files manually:

```bash
pip install huggingface_hub
huggingface-cli download hexgrad/Kokoro-82M-v1.1-zh \
  --local-dir models/ \
  --include "config.json" "kokoro-v1_1-zh.pth" "voices/*.pt"
```

Required layout:

```text
models/config.json
models/kokoro-v1_1-zh.pth
models/voices/*.pt
```

A normal `git clone` may only download Git LFS pointer files, not real model weights. Docker Compose profiles persist the Hugging Face cache to avoid repeated downloads after container recreation.

## Common configuration

| Variable | Default | Description |
|---|---|---|
| `KOKORO_MODEL_DIR` | `./models` | Model directory |
| `KOKORO_HOST` | `0.0.0.0` | Listen address |
| `KOKORO_PORT` | `8000` | Service port |
| `KOKORO_DEVICE` | `auto` | `auto` / `cpu` / `cuda` |
| `KOKORO_WORKERS` | `1` | Uvicorn workers; keep 1 for GPU |
| `KOKORO_MAX_CONCURRENT_REQUESTS` | `1` | Max in-process synthesis concurrency |
| `KOKORO_REQUEST_TIMEOUT_SECONDS` | `300` | Request timeout |
| `KOKORO_MAX_TEXT_LENGTH` | `10000` | Max input text length |
| `KOKORO_SEGMENT_LENGTH` | `100` | Target segment length |
| `KOKORO_DEFAULT_VOICE` | `zm_010` | Default voice |
| `KOKORO_STREAM_BINARY_ENABLED` | `true` | Enable binary WebSocket audio frames |
| `KOKORO_CACHE_ENABLED` | `true` | Enable LRU audio cache |
| `KOKORO_BATCH_ENABLED` | `true` | Enable batch synthesis |
| `KOKORO_ADMIN_ENABLED` | `false` | Enable admin APIs |
| `KOKORO_VOICE_UPLOAD_ENABLED` | `false` | Enable voice upload |
| `KOKORO_MP3_ENABLED` | `false` | Enable MP3 output |
| `KOKORO_API_KEY` | - | Bearer API key |
| `KOKORO_CORS_ORIGINS` | `http://localhost:8000` | Comma-separated CORS origins |

## Security notes

- Set `KOKORO_API_KEY` for public or semi-public deployments.
- Admin APIs are disabled by default. If enabled, use a strong API key and restrict access at the reverse proxy layer.
- `.pt` voice upload is disabled by default. Only upload trusted files; PyTorch weight files should not come from untrusted sources.
- Do not expose `/admin/*` directly to the public internet.
- `cancel/stop` prevents later segments from being sent. If the current segment is already inside synchronous inference, it usually stops after that segment completes.

See [Security Notes](docs/SECURITY.md).

## Known limitations

- AngeVoice does not train a new model; quality, license, and language capability follow the upstream Kokoro model.
- Long-form text is synthesized segment by segment. Very long books should use a batch/task workflow.
- For GPU deployments, avoid multiple workers loading the model at the same time unless you have enough VRAM.
- MP3 output depends on ffmpeg.
- WebSocket streaming is segment-level streaming, not true model-internal token streaming.

## Testing

```bash
pip install -e '.[dev]'
pytest -q --cov=kokoro_tts --cov-report=term-missing
```

Service smoke tests:

```bash
chmod +x scripts/smoke_test.sh scripts/loop_test.sh
BASE_URL=http://127.0.0.1:8101 ./scripts/smoke_test.sh
N=50 BASE_URL=http://127.0.0.1:8101 ./scripts/loop_test.sh
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Security Notes](docs/SECURITY.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Service Profiles](docs/SERVICE_PROFILES.md)
- [v2.5 Features](docs/V2_4_FEATURES.md)
- [Roadmap](docs/ROADMAP.md)
- [Legacy GPU Deployment](docker/legacy-gpu/README.md)

## License

MIT
