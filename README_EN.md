# AngeVoice

> Lightweight Chinese TTS self-hosted service. AngeVoice defaults to Kokoro v1.1 Chinese and can switch to MOSS-TTS-Nano on demand. It provides an OpenAI-compatible API, WebSocket streaming, Studio Web UI, MOSS reference-audio cloning, batch synthesis, cache, metrics, and Docker CPU/GPU/legacy-GPU profiles.

English | [中文](README.md)

[![CI](https://github.com/ang77712829/AngeVoice/actions/workflows/ci.yml/badge.svg)](https://github.com/ang77712829/AngeVoice/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

## One-command install (recommended)

After Docker and Docker Compose V2 are installed, run the interactive installer. It detects CPU/GPU, Docker/Compose, GitHub, GHCR, Docker Hub, and local Docker registry mirrors. When an NVIDIA GPU is found, it recommends the standard `gpu` profile first; `legacy-gpu` is a fallback for hosts where `gpu` cannot start or CUDA/cuDNN is incompatible.

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/ang77712829/AngeVoice/main/scripts/install.sh)
```

For restricted networks, clone the repository first and run the local installer:

```bash
git clone https://github.com/ang77712829/AngeVoice.git
cd AngeVoice
bash scripts/install.sh
```

Shared Docker defaults live in `docker/angevoice.env`. They are CPU/NAS-safe by default. The standard `gpu` profile is the recommended NVIDIA path; `legacy-gpu` is a CUDA 11.8 compatibility fallback.

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


## Xiaozhi ESP32 server adapter

This repository now includes a non-invasive `xiaozhi/` adapter kit for xiaozhi-esp32-server:

- `xiaozhi/adapters/angevoice.py`: non-streaming OpenAI-compatible TTS adapter.
- `xiaozhi/adapters/angevoice_stream.py`: WebSocket streaming adapter for Kokoro/MOSS.
- `xiaozhi/adapters/angevoice_clone.py`: non-streaming MOSS reference-audio clone adapter.
- `xiaozhi/scripts/install-xiaozhi-adapter.sh`: one-command installer for adapter files, Compose patching and example config.
- `xiaozhi/manager/presets.yaml`: copyable console presets; it does not modify xiaozhi frontend code.

Quick install from a xiaozhi server directory:

```bash
cd /path/to/xiaozhi-server
bash <(curl -fsSL https://raw.githubusercontent.com/ang77712829/AngeVoice/main/xiaozhi/scripts/install-xiaozhi-adapter.sh)
```

See [`xiaozhi/README.md`](xiaozhi/README.md) for the full Chinese guide.

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
| MOSS-TTS-Nano | OpenMOSS ONNX runtime adapter with preset voices, reference-audio cloning, CPU baseline, and experimental CUDA mode; process isolation is off by default to reduce process overhead on NAS/older GPUs, and can be enabled manually when hard isolation is required |
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

### Docker CPU / legacy-gpu fallback

```bash
# CPU, default port 8100
cd docker/cpu && sudo docker compose up -d

# legacy-gpu, default port 8102
# Use only when docker/gpu cannot start or CUDA/cuDNN is incompatible.
cd docker/legacy-gpu && sudo docker compose up -d
```

> Try `docker/gpu` first on NVIDIA hosts. Tesla P4/P40/V100 can also perform better with the standard `gpu` image when the host driver is recent; `legacy-gpu` is a compatibility fallback, not a guaranteed faster path.


### China Mirror Acceleration

Docker Compose pulls images from GHCR (`ghcr.io`) by default. If GHCR is slow from mainland China, use a Docker mirror proxy:

```bash
# Option 1: Pull via mirror, then retag (replace ghcr.io with mirror host)
docker pull docker.1ms.run/ghcr.io/ang77712829/angevoice-gpu:latest
docker tag docker.1ms.run/ghcr.io/ang77712829/angevoice-gpu:latest ghcr.io/ang77712829/angevoice-gpu:latest

# Option 2: Configure Docker daemon global mirror (recommended)
# Edit /etc/docker/daemon.json and add:
# { "registry-mirrors": ["https://docker.1ms.run"] }
# Then restart Docker: sudo systemctl restart docker
```

> Common mirrors: `docker.1ms.run`, `docker.xuanyuan.me`, `dockerpull.org`. Mirror availability may vary; try an alternative if one is down.

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
| Admin UI | `/admin` | Status, model controls, voice-quality tuning, API Key reveal/rotation |
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

A normal `git clone` or GitHub source archive may only include Git LFS pointer files. AngeVoice validates both `kokoro-v1_1-zh.pth` and `models/voices/*.pt`, skips LFS pointers, HTML/JSON error pages, and tiny incomplete files, and avoids passing those text placeholders to `torch.load`. This prevents `Weights only load failed` / `Unsupported operand 118` caused by LFS pointer files. Docker Compose profiles persist the Hugging Face / ModelScope cache to avoid repeated downloads after container recreation.

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
| `KOKORO_MAX_CONCURRENT_REQUESTS` | `1` | Max in-process synthesis concurrency; conservative for NAS/old GPUs, raise to 2-4 only on larger GPUs |
| `KOKORO_API_KEY` | - | Enables Bearer auth; `auto` generates and persists a strong random key on first start; placeholder values are rejected |
| `ANGEVOICE_API_KEY_FILE` | `/app/outputs/.angevoice-api-key` | Persistent key file used by `KOKORO_API_KEY=auto`; admin UI can reveal/rotate it |
| `ANGEVOICE_RUNTIME_CONFIG_FILE` | `/app/outputs/runtime-config.json` | Runtime settings saved by the admin UI; overrides environment variables and can be exported as an ENV patch |
| `KOKORO_STREAM_CHUNK_SECONDS` | `0.55` | WebSocket chunk duration |
| `KOKORO_CACHE_ENABLED` | `true` | Enable LRU audio cache |
| `KOKORO_BATCH_ENABLED` | `true` | Enable batch synthesis |
| `KOKORO_ADMIN_ENABLED` | Docker default `true` | Enable admin UI/API. Docker compose defaults to `admin` / `admin123`; change it for public deployments. |
| `KOKORO_MP3_ENABLED` | `false` | Enable MP3 output, requires ffmpeg |
| `ANGEVOICE_ENABLED_MODELS` | `kokoro,moss-nano-cpu` | Comma-separated enabled model IDs. GPU profiles override this and also expose `moss-nano-cuda`. |
| `ANGEVOICE_DEFAULT_MODEL` | `kokoro` | Startup model |
| `ANGEVOICE_MODEL_UNLOAD_ON_SWITCH` | `true` | Unload old engine when switching |
| `ANGEVOICE_SAVE_OUTPUTS` | `true` | Save HTTP synthesis outputs in Docker profiles; code default is `false` outside Docker |
| `ANGEVOICE_MODEL_SOURCE` | `auto` | Model download source: `auto` probes Hugging Face/ModelScope reachability first, then falls back to country detection; can be forced to `modelscope` / `huggingface` |
| `KOKORO_MODELSCOPE_REPO` | `AI-ModelScope/Kokoro-82M-v1.1-zh` | ModelScope Kokoro repository for China-friendly auto downloads |
| `MOSS_MODELSCOPE_REPO` | `openmoss/MOSS-TTS-Nano-100M-ONNX` | ModelScope MOSS ONNX repository for China-friendly auto downloads |
| `MOSS_MODEL_DIR` | - | MOSS ONNX model directory; auto source selection can populate it when omitted |
| `MOSS_EXECUTION_PROVIDER` | `cpu` | MOSS ONNX provider: `cpu` / `cuda` |
| `MOSS_CUDA_ENABLED` | `false` | Allow/register `moss-nano-cuda`; CPU/legacy-gpu keep it off, standard GPU enables it. |
| `MOSS_PROMPT_UPLOAD_MAX_BYTES` | `20971520` | MOSS clone reference-audio upload limit |
| `MOSS_SEGMENT_LENGTH` | `120` | MOSS-only stability-first segment length; reduces mixed-language drift, stutter and artifacts without changing Kokoro segmentation. |
| `MOSS_PROMPT_AUDIO_MAX_SECONDS` | `8` | Reference-audio trim duration |
| `MOSS_PROMPT_CACHE_MAX_ITEMS` | `8` | Encoded prompt-audio cache size |
| `MOSS_APPLY_ANGEVOICE_RULES` | `auto` | Text rules for MOSS: full Chinese normalization for Chinese-major text, conservative cleanup for mixed English/technical text |
| `MOSS_MIXED_ENGLISH_POLICY` | `translate` | Translate common mixed-English phrases into natural Chinese for MOSS; set `preserve` to keep original English |
| `MOSS_AUTO_FALLBACK_CPU` | `true` | Fall back to CPU when CUDA self-test fails |
| `MOSS_STREAM_PREBUFFER_SECONDS` | `0.75` | Browser prebuffer for MOSS streaming, reducing underflow on NAS/older GPUs |
| `MOSS_STREAM_QUEUE_MAX_ITEMS` | `8` | MOSS streaming queue depth to absorb short decode/browser/network jitter |
| `MOSS_PROCESS_ISOLATION_ENABLED` | `false` | Enable MOSS process isolation; loaded engines must be unloaded/rebuilt before this takes effect |
| `MOSS_PROCESS_ISOLATION_PROVIDERS` | `cuda` | Providers executed in an isolated worker process |
| `MOSS_PROCESS_KILL_GRACE_SECONDS` | `2` | Grace seconds before force-killing a timed-out worker |
| `MOSS_VRAM_SNAPSHOT_TTL_SECONDS` | `10` | Cache CUDA VRAM snapshots to avoid frequent torch/nvidia-smi probes during streaming |
| `MOSS_QUALITY_GATE_ENABLED` | `true` | Reject silent, NaN/Inf, or heavily clipped MOSS self-test output |
| `ANGEVOICE_IDLE_TIMEOUT_SECONDS` | `600` | Auto-unload all loaded models after N idle seconds; 0 = disabled |
| `ANGEVOICE_IDLE_CHECK_INTERVAL` | `30` | Idle check interval (seconds) |
| `MOSS_STREAM_BUDGET_THRESHOLD_LOW` | `0.25` | Audio lead low threshold in seconds; below this decode 1 frame for faster first audio |
| `MOSS_STREAM_BUDGET_THRESHOLD_MID` | `0.65` | Audio lead mid threshold; below this decode 2 frames |
| `MOSS_STREAM_BUDGET_THRESHOLD_HIGH` | `1.20` | Audio lead high threshold; below this decode 4 frames, above this decode 8 frames |
| `MOSS_STREAM_CHUNK_MIN_FLOOR` | `0.10` | Minimum stream chunk floor (seconds) to avoid tiny choppy fragments |
| `KOKORO_TRUST_PROXY_HEADERS` | `false` | Do not trust `X-Forwarded-For` by default; enable only behind a trusted reverse proxy |
| `KOKORO_PUBLIC_STATUS_ENDPOINTS` | `true` | Keep `/v1/models`, `/v1/models/current`, and `/v1/audio/voices` public; set false to require Bearer auth for them while leaving `/health` public |

## Security notes

- Set `KOKORO_API_KEY` for public or semi-public deployments; `KOKORO_API_KEY=auto` can generate a persistent random key on first start. The default Docker path is `outputs/.angevoice-api-key`.
- Docker compose enables the admin UI by default with `admin` / `admin123` for NAS first-run convenience. Public deployments must change `ANGEVOICE_ADMIN_PASSWORD`, set a strong API key, and restrict access at the reverse proxy.
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
- [MOSS Audio Quality](docs/MOSS_AUDIO_QUALITY.md)
- [Multi-Model Runtime](docs/MODEL_RUNTIME.md)
- [v2.6 Features](docs/V2_5_FEATURES.md)
- [Roadmap](docs/ROADMAP.md)
- [Legacy GPU Deployment](docker/legacy-gpu/README.md)

## License

AngeVoice project code is MIT.
Kokoro and MOSS-TTS-Nano remain under their upstream licenses.
See `THIRD_PARTY_NOTICES.md` and `ACKNOWLEDGEMENTS.md`.
