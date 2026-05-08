# AngeVoice

> Lightweight Chinese TTS self-hosted service. AngeVoice defaults to the Kokoro v1.1 Chinese model and can switch to MOSS-TTS-Nano on demand for low-power devices, NAS boxes, and long-running home services.

English | [中文](README.md)

[![CI](https://github.com/ang77712829/AngeVoice/actions/workflows/ci.yml/badge.svg)](https://github.com/ang77712829/AngeVoice/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

## What is AngeVoice?

AngeVoice is not a newly trained model. It is a local TTS service framework for low-power devices, NAS boxes, and long-running self-hosted environments. Kokoro v1.1 Chinese is the default engine; optional engines are integrated through the runtime model manager, starting with MOSS-TTS-Nano ONNX.

Good fits:

- Local/NAS/home-server Chinese speech synthesis
- TTS backend for agents, readers, audiobooks, and dubbing tools
- OpenAI-compatible TTS API backend
- Web apps that need segment playback, stop generation, and batch ZIP export
- CPU, NVIDIA GPU, and legacy/conservative CUDA environments

> Model source: the default engine is built on Kokoro v1.1 / Kokoro-82M Chinese. Optional MOSS-TTS-Nano support uses the official OpenMOSS runtime code. Model copyright, license, and restrictions follow the upstream repositories.

## Highlights

| Capability | Description |
|---|---|
| OpenAI-compatible API | `POST /v1/audio/speech` with `model/input/voice/speed/response_format` |
| Studio Web UI | Built-in page with light/dark themes, voice filtering, favorites, preview, streaming playback, stop generation, API-key settings, and collapsible metric cards |
| Multi-model runtime | `/v1/models` lists, loads, unloads, and switches engines; cache keys are isolated by model |
| MOSS-TTS-Nano | OpenMOSS ONNX runtime adapter with preset voices, reference-audio cloning, CPU baseline, and experimental CUDA mode |
| Chinese text rules | Auto pause punctuation, jieba-first segmentation, fallback lexicon, and common context-aware polyphone overrides |
| WebSocket streaming | `ws://.../ws/v1/tts` segment streaming with `cancel` / `stop` control frames |
| Batch synthesis | `POST /v1/audio/batch` returns a ZIP and `manifest.json` |
| Service controls | Request IDs, `/health`, `/stats`, `/requests`, timeout, concurrency guard, LRU cache |
| Admin APIs | Optional cache clearing, voice listing, and `.pt` voice upload |
| Output formats | WAV, PCM s16le, optional MP3 through ffmpeg |
| Docker | CPU, GPU, and Legacy GPU Compose profiles |
| CLI | Recommended command: `angevoice`; legacy `kokoro-tts` remains supported |

## v2.6 modular refactor

v2.6 splits the previously heavy `server.py` into focused modules while keeping the public entry points compatible:

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
├── zh_rules.py           # Chinese punctuation, polyphone, and lightweight segmentation rules
├── audio.py              # WAV / PCM encoding helpers
├── engine_manager.py     # model registration, loading, switching, and unloading
├── engine.py             # Kokoro engine, segmentation, normalization, audio encoding
├── moss_engine.py        # MOSS-TTS-Nano official ONNX runtime adapter
├── config.py             # configuration and environment variables
├── templates/index.html  # Studio Web UI shell
└── static/               # Studio Web UI styles and scripts
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

Docker images now preinstall the matching MOSS runtime for each service profile.
MOSS model assets are downloaded only when a MOSS model is first loaded:

- CPU exposes `kokoro,moss-nano-cpu` and never exposes CUDA MOSS.
- Modern GPU exposes `kokoro,moss-nano-cpu,moss-nano-cuda`; startup still loads `kokoro`, and users can switch models in the Web UI. MOSS clone mode shows the reference-audio upload only when the selected model supports it.
- Legacy GPU also preinstalls MOSS GPU dependencies, but its Compose profile exposes only `kokoro,moss-nano-cpu` by default. Add `moss-nano-cuda` and set `MOSS_CUDA_ENABLED=true` only after validating the old card/driver stack.

CUDA mode runs provider and audio-quality self-tests first. A Docker probe on Tesla P4 passed the modern GPU profile with `onnxruntime-gpu==1.20.2` plus `nvidia-cudnn-cu12==9.1.0.70`. If cuDNN 9 is missing or provider self-test fails, AngeVoice falls back to CPU.

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

Model management:

```bash
curl http://localhost:8000/v1/models

curl -X POST http://localhost:8000/v1/models/switch \
  -H "Content-Type: application/json" \
  -d '{"model":"moss-nano-cpu","unload_previous":true}'
```

## API examples

### OpenAI-compatible TTS

```bash
curl -X POST http://localhost:8000/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"model":"kokoro","input":"Hello world","voice":"zm_010","response_format":"wav"}' \
  --output output.wav
```

MOSS reference-audio cloning uses multipart upload on `/api/tts`. The Studio Web UI only shows the reference-audio control when the selected model supports `voice_clone`:

```bash
curl -X POST http://localhost:8000/api/tts \
  -F model=moss-nano-cpu \
  -F text="This is a reference-audio clone test." \
  -F voice=Junhao \
  -F response_format=wav \
  -F prompt_audio=@reference.wav \
  --output clone.wav
```

Uploading reference audio to a non-clone model such as Kokoro returns 400.

WebSocket streaming also supports MOSS clone mode. The first JSON message can
carry `prompt_audio.data` as base64 or a data URL. The Studio UI does this
automatically when a reference file is selected and streaming is enabled:

```json
{
  "model": "moss-nano-cpu",
  "text": "This is a streamed reference-audio clone test.",
  "voice": "Junhao",
  "format": "pcm_s16le",
  "prompt_audio": {
    "filename": "reference.wav",
    "data": "<base64>"
  }
}
```

When `KOKORO_API_KEY` is enabled, add:

```bash
-H "Authorization: Bearer YOUR_TOKEN"
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
    binary: false,
    token: "YOUR_TOKEN" // omit when KOKORO_API_KEY is disabled
  }));
};

ws.send(JSON.stringify({ type: "cancel" }));
```

Message types: `started`, `audio`, `segment_error`, `done`, `cancelled`, `error`.

JSON audio frames carry base64 PCM in the `data` field. When binary mode is enabled, the service sends a metadata JSON frame followed by binary audio bytes.

### Chinese rule examples

Before text reaches the Kokoro pipeline, AngeVoice applies lightweight Chinese rules:

```text
春花秋月何时了 -> 春花秋月何时瞭。
我想了解一下 -> 我想瞭解一下
银行行长正在听音乐 -> 银杭杭掌正在听音悦
会议12:01开始 -> 会议十二点零一分开始
Long Chinese input without punctuation -> word-aware pause punctuation
```

The rules target common reading mistakes. For complex names, places, and domain-specific terms, prefer explicit punctuation or future dictionary/SSML support.

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

## Docker persistence

All Compose profiles prepare these host mounts:

| Host path | Container path | Purpose |
|---|---|---|
| `../../hf_cache` | `/root/.cache/huggingface` | Kokoro/Hugging Face download cache |
| `../../moss_models` | `/opt/MOSS-TTS-Nano/models` | MOSS ONNX asset cache, preserved after first download |
| `../../outputs` | `/app/outputs` | HTTP synthesis outputs when `ANGEVOICE_SAVE_OUTPUTS=true` |

Output files are grouped by date and pruned by `ANGEVOICE_OUTPUT_MAX_FILES`. MOSS internal temporary files stay inside the container temp directory and do not pollute the persistent output mount.

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
| `KOKORO_API_KEY` | - | Bearer API key; placeholder values such as `change-me` are rejected |
| `KOKORO_CORS_ORIGINS` | `http://localhost:8000` | Comma-separated CORS origins |
| `ANGEVOICE_ENABLED_MODELS` | `kokoro` | Comma-separated enabled model IDs |
| `ANGEVOICE_DEFAULT_MODEL` | `kokoro` | Model loaded on startup |
| `ANGEVOICE_MODEL_UNLOAD_ON_SWITCH` | `true` | Unload the previous engine when switching |
| `ANGEVOICE_SAVE_OUTPUTS` | `false` | Save HTTP synthesis outputs |
| `ANGEVOICE_OUTPUT_DIR` | `/app/outputs` | Output directory |
| `ANGEVOICE_OUTPUT_MAX_FILES` | `1000` | Max retained output files; `0` disables pruning |
| `MOSS_TTS_NANO_PATH` | - | Local path to the official OpenMOSS/MOSS-TTS-Nano repo |
| `MOSS_MODEL_DIR` | - | MOSS ONNX asset directory; Docker uses `/opt/MOSS-TTS-Nano/models` |
| `MOSS_EXECUTION_PROVIDER` | `cpu` | MOSS ONNX provider: `cpu` / `cuda` |
| `MOSS_CUDA_ENABLED` | `true` | Allow registering/switching `moss-nano-cuda`; CPU/legacy profiles disable it |
| `MOSS_CPU_THREADS` | `4` | MOSS CPU ONNX thread count; 2-4 is usually safer on NAS boxes |
| `MOSS_PROMPT_UPLOAD_MAX_BYTES` | `20971520` | Reference-audio upload size limit |
| `MOSS_PROMPT_AUDIO_MAX_SECONDS` | `10` | Trim clone reference audio to reduce VRAM use and latency |
| `MOSS_PROMPT_CACHE_MAX_ITEMS` | `8` | Cache encoded reference audio codes for repeated clone requests |
| `MOSS_APPLY_ANGEVOICE_RULES` | `true` | Apply AngeVoice Chinese semantic, punctuation, and polyphone rules to MOSS/future adapters |
| `MOSS_AUTO_FALLBACK_CPU` | `true` | Fall back to CPU when CUDA self-test fails |
| `MOSS_QUALITY_GATE_ENABLED` | `true` | Reject silent, NaN/Inf, or heavily clipped MOSS self-test output |
| `MOSS_OUTPUT_PEAK_NORMALIZE_ENABLED` | `true` | Peak-normalize MOSS output to reduce clipping/crackle risk |
| `MOSS_OUTPUT_TARGET_PEAK` | `0.92` | MOSS output target peak |
| `MOSS_OUTPUT_GAIN` | `1.0` | Extra MOSS output gain; do not raise it when debugging artifacts |

## Security notes

- Set `KOKORO_API_KEY` for public or semi-public deployments.
- Admin APIs are disabled by default. If enabled, a strong API key is required or the service refuses to start.
- `.pt` voice upload is disabled by default. Only upload trusted files; PyTorch weight files should not come from untrusted sources.
- Do not expose `/admin/*` directly to the public internet.
- `cancel/stop` prevents later segments from being sent. If the current segment is already inside synchronous inference, it usually stops after that segment completes.

See [Security Notes](docs/SECURITY.md).

## Known limitations

- AngeVoice does not train a new model; quality, license, and language capability follow the upstream models.
- The project is optimized for stable local TTS on low-power devices, NAS boxes, and long-running services. It prioritizes interactive speed, controlled resource usage, and maintainability; audio quality ceilings follow upstream models.
- Docker profiles preinstall their matching MOSS runtime, but startup still loads Kokoro; MOSS assets are downloaded on demand into the persistent model directory.
- `moss-nano-cuda` is experimental. Tesla P4 has been verified, but long-running service should still be enabled only after target-host listening tests confirm no crackle, distortion, or clipping.
- Long-form text is synthesized segment by segment. Very long books should use a batch/task workflow.
- For GPU deployments, avoid multiple workers loading the model at the same time unless you have enough VRAM.
- MP3 output depends on ffmpeg.
- WebSocket streaming is segment-level streaming. MOSS clone mode can upload reference audio in the first message, but it is still not true model-internal token streaming.

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
- [Multi-Model Runtime](docs/MODEL_RUNTIME.md)
- [v2.6 Features](docs/V2_5_FEATURES.md)
- [Roadmap](docs/ROADMAP.md)
- [Legacy GPU Deployment](docker/legacy-gpu/README.md)

## License

MIT
