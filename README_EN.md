# AngeVoice

> Lightweight Chinese TTS self-hosted service. AngeVoice defaults to Kokoro v1.1 Chinese and can switch to MOSS-TTS-Nano on demand. It provides an OpenAI-compatible API, WebSocket streaming, Studio Web UI, MOSS reference-audio cloning, batch synthesis, cache, metrics, and Docker CPU/GPU/legacy-GPU profiles.

English | [中文](README.md)

[![CI](https://github.com/ang77712829/AngeVoice/actions/workflows/ci.yml/badge.svg)](https://github.com/ang77712829/AngeVoice/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)


## One-command install (recommended)

After Docker and Docker Compose V2 are installed, run the interactive installer. It detects CPU/GPU, older NVIDIA cards, Docker/Compose, GitHub, GHCR, Docker Hub, and local Docker registry mirrors, then recommends the `cpu`, `gpu` or `legacy-gpu` profile.

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/ang77712829/AngeVoice/main/scripts/install.sh)
```

For restricted networks, clone the repository first and run the local installer:

```bash
git clone https://github.com/ang77712829/AngeVoice.git
cd AngeVoice
bash scripts/install.sh
```

Shared Docker defaults live in `docker/angevoice.env`. They are CPU/NAS-safe by default; GPU profiles only override the required CUDA settings.

When the script is run from an existing source checkout, it installs/updates **in place** and no longer clones another copy into `/opt/angevoice`, which is friendlier for NAS file managers. The `/opt/angevoice` fallback is only used for remote `curl` installs where no local project directory exists. After startup, the script prints the detected LAN URL, for example `http://192.168.1.10:8101`.

After installation, the script creates the `AngeVoice` management command. Run:

```bash
AngeVoice
```

It opens a menu for install/update, restart, stop, uninstall, status and access URLs. Direct commands are also available:

```bash
bash scripts/install.sh --status
bash scripts/install.sh --restart
bash scripts/install.sh --stop
bash scripts/install.sh --uninstall
```

Uninstall stops/removes containers and networks only; models, outputs and config files are kept.

## What is AngeVoice?

AngeVoice is not a newly trained model. It is a local TTS service framework for low-power devices, NAS boxes, and long-running self-hosted environments.

Good fits:

- Local/NAS/home-server Chinese speech synthesis
- TTS backend for agents, readers, audiobooks, and dubbing tools
- OpenAI-compatible TTS API backend
- Web apps that need segment playback, stop generation, and batch ZIP export
- CPU, NVIDIA GPU, and legacy/conservative CUDA environments

> Model source: the default engine is built on Kokoro v1.1 / Kokoro-82M Chinese. MOSS-TTS-Nano integration uses the official OpenMOSS runtime code. Model copyright, license, and restrictions follow upstream repositories.

## Studio preview

![AngeVoice Studio model switch](docs/assets/studio-model-switch.png)

![AngeVoice Studio reference-audio clone](docs/assets/studio-voice-clone.png)

## Highlights

| Capability | Description |
|---|---|
| Studio Web UI | Built-in console with model switching, voice filtering, preview, streaming playback, stop generation, API-key settings, and metrics |
| API docs page | `GET /api-docs` provides copyable examples, especially for MOSS reference-audio clone and streaming clone |
| OpenAI-compatible API | `POST /v1/audio/speech` with `model/input/voice/speed/response_format` |
| MOSS-TTS-Nano | OpenMOSS ONNX runtime adapter with preset voices, reference-audio cloning, CPU baseline, and experimental CUDA mode; CUDA uses process isolation by default so a stuck worker can be killed |
| Multi-model runtime | `/v1/models` lists, loads, unloads, and switches engines; cache keys are isolated by model |
| WebSocket streaming | `WS /ws/v1/tts`; bounded chunks, `cancel` / `stop`, MOSS clone audio in the first JSON message |
| Chinese text rules | Auto pause punctuation, jieba-first segmentation, fallback lexicon, and common polyphone overrides |
| Batch synthesis | `POST /v1/audio/batch` returns a ZIP and `manifest.json` |
| Service controls | Request IDs, `/health`, `/stats`, `/requests`, timeout, concurrency guard, LRU cache |
| Docker profiles | CPU, GPU, and Legacy GPU Compose profiles |
| CLI | Recommended command: `angevoice`; legacy `kokoro-tts` remains supported |
| Idle timeout release | Defaults to unloading all loaded models after 10 minutes of inactivity, including the current model, to reduce NAS power/VRAM usage |

## Quick start

### Docker GPU

```bash
git clone https://github.com/ang77712829/AngeVoice.git
cd AngeVoice/docker/gpu
sudo docker compose up -d
```

Default URL:

```text
http://localhost:8101
```

Check the service:

```bash
curl http://127.0.0.1:8101/health
curl http://127.0.0.1:8101/v1/models
```

> **Container health status**: Every Docker image includes a built-in `HEALTHCHECK` that hits `/health` every 30 seconds. A `{"status":"ok"}` or `{"status":"idle"}` response marks the container as **healthy**. `idle` means the current model was unloaded by the idle timer but the service is ready to auto-load it on the next request. The 60-second start period allows model loading before the first check. Inspect with `docker inspect --format='{{json .State.Health}}' <container>`.

### Docker CPU / Legacy GPU

```bash
# CPU, default port 8100
cd docker/cpu && sudo docker compose up -d

# Legacy GPU, default port 8102
cd docker/legacy-gpu && sudo docker compose up -d
```

### Editable pip install

```bash
git clone https://github.com/ang77712829/AngeVoice.git
cd AngeVoice
pip install -e .

angevoice serve --port 8000
angevoice synth "Hello world" -o hello.wav -v zm_010

# Legacy command still works
kokoro-tts serve --port 8000
```


### `/health` status semantics

| status | Meaning |
|---|---|
| `ok` | Service is healthy and the current model is loaded |
| `idle` | Service is healthy, but the current model was unloaded by the idle timer and will auto-load on next request |
| `loading` | Service is up but the current model is still loading or has not completed first load |
| `degraded` | At least one loaded model is unhealthy |

Docker health checks treat both `ok` and `idle` as healthy.

## Documentation entry points

| Entry | Path | Purpose |
|---|---|---|
| Studio | `/` | Web synthesis, preview, model switching |
| API docs page | `/api-docs` | User-friendly copyable HTTP/WebSocket/MOSS clone examples |
| Swagger | `/docs` | FastAPI interactive API docs |
| ReDoc | `/redoc` | FastAPI readable docs |
| API Reference | [`docs/API_REFERENCE.md`](docs/API_REFERENCE.md) | Full repository API reference |
| Troubleshooting | [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) | Common deployment and client issues |

## Ports and endpoint overview

| Profile | HTTP / Web UI | WebSocket |
|---|---|---|
| pip / development | `http://localhost:8000` | `ws://localhost:8000/ws/v1/tts` |
| Docker CPU | `http://localhost:8100` | `ws://localhost:8100/ws/v1/tts` |
| Docker GPU | `http://localhost:8101` | `ws://localhost:8101/ws/v1/tts` |
| Docker Legacy GPU | `http://localhost:8102` | `ws://localhost:8102/ws/v1/tts` |

| Capability | Endpoint |
|---|---|
| Health / metrics / requests | `GET /health`, `GET /stats`, `GET /requests` |
| Model list / current / switch | `GET /v1/models`, `GET /v1/models/current`, `POST /v1/models/switch` |
| Voices / formats | `GET /v1/audio/voices`, `GET /v1/audio/formats` |
| OpenAI-compatible speech | `POST /v1/audio/speech` |
| Legacy speech / MOSS clone upload | `GET /api/tts`, `POST /api/tts` |
| WebSocket streaming / MOSS clone streaming | `WS /ws/v1/tts` |
| Batch ZIP | `POST /v1/audio/batch` |
| Cancel request | `POST /v1/audio/requests/{request_id}/cancel` |

## Common API examples

### OpenAI-compatible TTS

```bash
BASE_URL=http://localhost:8000

curl -X POST "$BASE_URL/v1/audio/speech" \
  -H "Content-Type: application/json" \
  -d '{"model":"kokoro","input":"Hello world","voice":"zm_010","response_format":"wav"}' \
  --output output.wav
```

When `KOKORO_API_KEY` is enabled, add:

```bash
-H "Authorization: Bearer YOUR_TOKEN"
```

### MOSS reference-audio clone

MOSS clone does **not** use `models/voices`. That directory is for Kokoro `.pt` voices.

The recommended path is uploading the reference audio with the request:

```bash
curl -X POST "$BASE_URL/api/tts" \
  -F model=moss-nano-cpu \
  -F text="This is a reference-audio clone test." \
  -F voice=Junhao \
  -F response_format=wav \
  -F prompt_audio=@reference.wav \
  --output clone.wav
```

WebSocket streaming clone carries reference audio in the first JSON message:

```json
{
  "model": "moss-nano-cpu",
  "text": "This is a streamed reference-audio clone test.",
  "voice": "Junhao",
  "format": "pcm_s16le",
  "prompt_audio": {
    "filename": "reference.wav",
    "data": "<base64-or-data-url>"
  }
}
```

Full browser FileReader, Python websockets, and Docker default-reference-audio examples:

- [`/api-docs`](http://localhost:8000/api-docs)
- [`docs/API_REFERENCE.md`](docs/API_REFERENCE.md)

## Model files

If local model files are not found, the service falls back to Hugging Face download. For offline deployments or faster cold starts:

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

A normal `git clone` may only download Git LFS pointer files. Docker Compose profiles persist the Hugging Face cache to avoid repeated downloads after container recreation.

## Docker persistence

| Host path | Container path | Purpose |
|---|---|---|
| `../../hf_cache` | `/root/.cache/huggingface` | Kokoro/Hugging Face cache |
| `../../moss_models` | `/opt/MOSS-TTS-Nano/models` | MOSS ONNX asset cache |
| `../../outputs` | `/app/outputs` | HTTP synthesis outputs when `ANGEVOICE_SAVE_OUTPUTS=true` |

To set a server-side default MOSS reference audio:

```yaml
volumes:
  - ../../prompts:/app/prompts:ro

environment:
  - MOSS_PROMPT_AUDIO_PATH=/app/prompts/reference.wav
```

## Key configuration

| Variable | Default | Description |
|---|---|---|
| `KOKORO_DEVICE` | `auto` | `auto` / `cpu` / `cuda` |
| `KOKORO_WORKERS` | `1` | Uvicorn workers; keep 1 for GPU |
| `KOKORO_MAX_CONCURRENT_REQUESTS` | `1` | Max in-process synthesis concurrency |
| `KOKORO_API_KEY` | - | Enables Bearer auth; placeholder values are rejected |
| `KOKORO_STREAM_CHUNK_SECONDS` | `0.50` | WebSocket chunk duration |
| `KOKORO_CACHE_ENABLED` | `true` | Enable LRU audio cache |
| `KOKORO_BATCH_ENABLED` | `true` | Enable batch synthesis |
| `KOKORO_ADMIN_ENABLED` | `false` | Enable admin APIs |
| `KOKORO_MP3_ENABLED` | `false` | Enable MP3 output, requires ffmpeg |
| `ANGEVOICE_ENABLED_MODELS` | `kokoro` | Comma-separated enabled model IDs |
| `ANGEVOICE_DEFAULT_MODEL` | `kokoro` | Startup model |
| `ANGEVOICE_MODEL_UNLOAD_ON_SWITCH` | `true` | Unload old engine when switching |
| `ANGEVOICE_SAVE_OUTPUTS` | `false` | Save HTTP synthesis outputs |
| `MOSS_MODEL_DIR` | - | MOSS ONNX model directory |
| `MOSS_EXECUTION_PROVIDER` | `cpu` | MOSS ONNX provider: `cpu` / `cuda` |
| `MOSS_CUDA_ENABLED` | `true` | Allow registering/switching `moss-nano-cuda` |
| `MOSS_PROMPT_UPLOAD_MAX_BYTES` | `20971520` | MOSS clone reference-audio upload limit |
| `MOSS_PROMPT_AUDIO_MAX_SECONDS` | `10` | Reference-audio trim duration |
| `MOSS_PROMPT_CACHE_MAX_ITEMS` | `8` | Encoded prompt-audio cache size |
| `MOSS_AUTO_FALLBACK_CPU` | `true` | Fall back to CPU when CUDA self-test fails |
| `MOSS_PROCESS_ISOLATION_ENABLED` | `true` | Enable MOSS process isolation |
| `MOSS_PROCESS_ISOLATION_PROVIDERS` | `cuda` | Providers executed in an isolated worker process |
| `MOSS_PROCESS_KILL_GRACE_SECONDS` | `2` | Grace seconds before force-killing a timed-out worker |
| `MOSS_QUALITY_GATE_ENABLED` | `true` | Reject silent, NaN/Inf, or heavily clipped MOSS self-test output |
| `ANGEVOICE_IDLE_TIMEOUT_SECONDS` | `600` | Auto-unload all loaded models after N idle seconds; 0 = disabled |
| `ANGEVOICE_IDLE_CHECK_INTERVAL` | `30` | Idle check interval (seconds) |
| `MOSS_STREAM_BUDGET_THRESHOLD_LOW` | `0.25` | Audio lead low threshold in seconds; below this decode 1 frame for faster first audio |
| `MOSS_STREAM_BUDGET_THRESHOLD_MID` | `0.65` | Audio lead mid threshold; below this decode 2 frames |
| `MOSS_STREAM_BUDGET_THRESHOLD_HIGH` | `1.20` | Audio lead high threshold; below this decode 4 frames, above this decode 8 frames |
| `MOSS_STREAM_CHUNK_MIN_FLOOR` | `0.10` | Minimum stream chunk floor (seconds) to avoid tiny choppy fragments |

## Security notes

- Set `KOKORO_API_KEY` for public or semi-public deployments.
- Admin UI/APIs are disabled by default. If enabled, `ANGEVOICE_ADMIN_PASSWORD` is required; public deployments should also set `KOKORO_API_KEY` and restrict access at the reverse proxy.
- `.pt` voice upload is disabled by default. Only upload trusted files.

⚠️ **Security Warning**: Enabling `KOKORO_VOICE_UPLOAD_ENABLED` on public-facing servers is **strongly discouraged**.
Only upload `.pt` files you generated yourself or from fully trusted sources.
If upload must be enabled, restrict to internal network admin endpoints with reverse-proxy IP whitelisting.
`.pt` files use PyTorch serialization which can theoretically execute arbitrary code.
- Do not expose `/admin/*` directly to the public internet.

See [`docs/SECURITY.md`](docs/SECURITY.md).

## Known limitations

- AngeVoice does not train a new model; quality, license, and language capability follow upstream models.
- `moss-nano-cuda` is experimental. Test on the target host before long-running service.
- Long-form text is synthesized segment by segment. Very long books should use a batch/task workflow.
- For GPU deployments, avoid multiple workers loading the model at the same time unless you have enough VRAM.
- MP3 output depends on ffmpeg.
- WebSocket streaming sends bounded audio chunks, not token-level speech generation.

## Testing

```bash
pip install -e '.[dev]'
pytest -q --cov=kokoro_tts --cov-report=term-missing
```

End-to-end testing (requires a running service):

```bash
# Full E2E loop test: health / voices / synthesis / websocket / cancel / idle unload / stress
chmod +x scripts/e2e_loop_test.sh
./scripts/e2e_loop_test.sh http://127.0.0.1:8101              # no auth, 10 loops
./scripts/e2e_loop_test.sh http://127.0.0.1:8101 my-key 50    # with auth, 50 loops
```

Lightweight smoke tests:

You can also manually trigger the `Docker CPU Smoke` GitHub Actions workflow to validate `docker compose config --quiet`, CPU image build, container startup, `/health`, and `scripts/smoke_test.sh`.

```bash
chmod +x scripts/smoke_test.sh scripts/loop_test.sh
BASE_URL=http://127.0.0.1:8101 ./scripts/smoke_test.sh
N=50 BASE_URL=http://127.0.0.1:8101 ./scripts/loop_test.sh
```

## More docs

- [Architecture](docs/ARCHITECTURE.md)
- [API Reference](docs/API_REFERENCE.md)
- [Security Notes](docs/SECURITY.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Service Profiles](docs/SERVICE_PROFILES.md)
- [Multi-Model Runtime](docs/MODEL_RUNTIME.md)
- [v2.6 Features](docs/V2_5_FEATURES.md)
- [Roadmap](docs/ROADMAP.md)
- [Legacy GPU Deployment](docker/legacy-gpu/README.md)

## License

MIT
