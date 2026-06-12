# AngeVoice

> Lightweight Chinese TTS self-hosted service. AngeVoice defaults to Kokoro v1.1 Chinese and can switch to MOSS-TTS-Nano on demand. It provides an OpenAI-compatible API, WebSocket streaming, Studio Web UI, in-browser recording, generic voice-profile/reference-audio management, batch synthesis, cache, metrics, and Docker CPU/GPU/legacy-GPU deployments.

English | [中文](README.md) | [Documentation index](docs/README.md)

[![CI](https://github.com/ang77712829/AngeVoice/actions/workflows/ci.yml/badge.svg)](https://github.com/ang77712829/AngeVoice/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-green.svg)](LICENSE)

## One-command install (recommended)

After Docker and Docker Compose V2 are installed, run the interactive installer. It detects CPU/GPU, Docker/Compose, GitHub, Docker Hub, and local Docker registry mirrors. When an NVIDIA GPU is found, it recommends the standard `gpu` profile first; `legacy-gpu` is a compatibility profile for hosts where `gpu` cannot start or CUDA/cuDNN is incompatible.

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/ang77712829/AngeVoice/main/scripts/install.sh)
```

For restricted networks, clone the repository first and run the local installer:

```bash
git clone https://github.com/ang77712829/AngeVoice.git
cd AngeVoice
bash scripts/install.sh
```

Shared Docker defaults live in `docker/angevoice.env`. The protected admin UI is enabled by default and new deployments can enter with `admin / admin123`; the security panel prominently requires changing those credentials before public exposure, and changed passwords are stored only as hashes. The standard `gpu` profile is the recommended NVIDIA path; `legacy-gpu` is a compatibility profile.

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

> Core upstream projects: the default engine is built on Kokoro v1.1 / Kokoro-82M Chinese; MOSS-TTS-Nano uses the official OpenMOSS runtime; ZipVoice provides zero-shot voice cloning. All three core upstream projects use the Apache License 2.0; see `THIRD_PARTY_NOTICES.md` and `ACKNOWLEDGEMENTS.md` for attribution.

## Studio preview

![AngeVoice Studio model switch](docs/assets/studio-model-switch.png)

![AngeVoice Studio reference-audio clone](docs/assets/studio-voice-clone.png)

## Highlights

| Capability | Description |
|---|---|
| Studio Web UI | Built-in console with model switching, browser recording/reference upload, Voice Profile save/preview/delete, streaming playback, stop generation, API-key settings, and metrics |
| API docs page | `GET /api-docs` provides copyable examples, especially for MOSS reference-audio clone and streaming clone |
| OpenAI-compatible API | `POST /v1/audio/speech` with `model/input/voice/speed/response_format` |
| MOSS-TTS-Nano | OpenMOSS ONNX runtime adapter with preset voices and reference-audio cloning; the stable product name is independent of the actual CPU/CUDA provider reported by diagnostics |
| Multi-model runtime | `/v1/models` lists, loads, unloads, and switches engines; cache keys are isolated by model |
| TTS capabilities | `GET /v1/tts/capabilities` returns current model capabilities, available encodings, and voice details |
| WebSocket streaming | `WS /ws/v1/tts`; bounded chunks, `cancel` / `stop`, MOSS clone audio in the first JSON message |
| Chinese text rules | Auto pause punctuation, jieba-first segmentation, fallback lexicon, and common polyphone overrides |
| Batch synthesis | `POST /v1/audio/batch` returns a ZIP and `manifest.json` |
| Service controls | Request IDs, `/health`, `/stats`, `/requests`, timeout, concurrency guard, LRU cache |
| Docker profiles | CPU, GPU, and Legacy GPU Compose profiles |
| CLI | `kokoro-tts serve`（also supports `python -m kokoro_tts.main serve`） |
| Idle resource release | Defaults to unloading all loaded models after 10 minutes of inactivity; an optional admin switch can exit after idle unload so Docker/service managers restart the container and reclaim low-level runtime leftovers |

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

Docker Compose pulls Docker Hub images (`maxblack777/angevoice-*:latest`) by default. If Docker Hub is slow from mainland China, use a Docker mirror proxy:

```bash
# Option 1: Pull via mirror, then retag
docker pull docker.1ms.run/maxblack777/angevoice-gpu:latest
docker tag docker.1ms.run/maxblack777/angevoice-gpu:latest maxblack777/angevoice-gpu:latest

# Option 2: Configure Docker daemon global mirror (recommended)
# Edit /etc/docker/daemon.json and add:
# { "registry-mirrors": ["https://docker.1ms.run"] }
# Then restart Docker: sudo systemctl restart docker
```

> Common mirrors: `docker.1ms.run`, `docker.xuanyuan.me`, `dockerpull.org`. Mirror availability may vary; try an alternative if one is down.

### pip development install

> **Requires Python 3.10 – 3.12**（3.13+ not yet supported by PyTorch）.

```bash
git clone https://github.com/ang77712829/AngeVoice.git
cd AngeVoice
pip install -e .
```

Start the server:

```bash
python -m kokoro_tts.main serve --port 8000
# Legacy command still works
kokoro-tts serve --port 8000
```

Test with browser or curl（replace with your actual IP）:

```bash
curl http://192.168.1.10:8000/health
curl -X POST http://192.168.1.10:8000/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"model":"kokoro","input":"Hello world","voice":"zm_010","response_format":"wav"}' \
  --output hello.wav
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
| Voices / formats | `GET /v1/audio/voices` (supports `?detail=true` for gender/display name), `GET /v1/audio/formats` |
| TTS capabilities | `GET /v1/tts/capabilities` |
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

MOSS clone does **not** use `models/models--hexgrad--Kokoro-82M-v1.1-zh/voices`. That directory is for Kokoro `.pt` voices.

The recommended path is uploading the reference audio with the request:

```bash
curl -X POST "$BASE_URL/api/tts" \
  -F model=moss \
  -F text="This is a reference-audio clone test." \
  -F voice=Junhao \
  -F response_format=wav \
  -F prompt_audio=@reference.wav \
  --output clone.wav
```

WebSocket streaming clone carries reference audio in the first JSON message:

```json
{
  "model": "moss",
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

If local model files are not found, the service falls back to Hugging Face download. For offline deployments or faster cold starts, set `ANGEVOICE_MODEL_SOURCE=offline` only after preparing complete local model assets:

```bash
pip install huggingface_hub
mkdir -p models/models--hexgrad--Kokoro-82M-v1.1-zh
huggingface-cli download hexgrad/Kokoro-82M-v1.1-zh \
  --local-dir models/models--hexgrad--Kokoro-82M-v1.1-zh \
  --include "config.json" "kokoro-v1_1-zh.pth" "voices/*.pt"
```

Recommended unified model layout:

```text
models/
├── models--hexgrad--Kokoro-82M-v1.1-zh/
│   ├── config.json
│   ├── kokoro-v1_1-zh.pth
│   └── voices/*.pt
├── MOSS-TTS-Nano-100M-ONNX/
└── modelscope-cache/
```

A normal `git clone` or GitHub source archive may only include Git LFS pointer files. AngeVoice validates both the Kokoro main model and voice files, skips LFS pointers, HTML/JSON error pages, and incomplete files, and avoids passing those text placeholders to `torch.load`. Kokoro voice files can be much smaller than the main model, so validation now checks file signatures first and no longer spams logs for the same 131-byte LFS pointer during long synthesis.

## Docker persistence

| Host path | Container path | Purpose |
|---|---|---|
| `../../models` | `/app/models` | Unified model directory for Kokoro, Hugging Face cache, ModelScope cache, and MOSS ONNX assets |
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
| `KOKORO_RATE_LIMIT_QPS` | `10` | Per API-key/client-IP rate limit; set 0 only for trusted local networks or protected reverse proxies |
| `KOKORO_RATE_LIMIT_BURST` | `20` | Token-bucket burst capacity per client |
| `KOKORO_MAX_QUEUE_LENGTH` | `50` | Maximum concurrent in-flight HTTP requests; 0 disables this guard |
| `KOKORO_WS_MAX_CONNECTIONS` | `16` | Maximum simultaneous WebSocket sessions; 0 disables this guard |
| `KOKORO_WS_MAX_MESSAGE_BYTES` | `33554432` | Maximum inbound WebSocket JSON message size; sized for a 20 MiB base64 reference-audio payload |
| `KOKORO_API_KEY` | - | Enables Bearer auth; `auto` generates and persists a strong random key on first start; placeholder values are rejected |
| `ANGEVOICE_API_KEY_FILE` | `/app/credentials/.angevoice-api-key` | Persistent key file used by `KOKORO_API_KEY=auto`; admin UI can reveal/rotate it |
| `ANGEVOICE_RUNTIME_CONFIG_FILE` | `/app/config/runtime-config.json` | Runtime settings saved by the admin UI; overrides environment variables and can be exported as an ENV patch |
| `KOKORO_STREAM_CHUNK_SECONDS` | `0.55` | WebSocket chunk duration |
| `KOKORO_CACHE_ENABLED` | `true` | Enable LRU audio cache |
| `KOKORO_BATCH_ENABLED` | `true` | Enable batch synthesis |
| `KOKORO_ADMIN_ENABLED` | `true` in Docker templates | The admin UI/API is available behind authentication. New deployments can sign in with `admin / admin123`; change the credentials before public exposure. |
| `KOKORO_MP3_ENABLED` | `false` | Enable MP3 output, requires ffmpeg |
| `ANGEVOICE_ENABLED_MODELS` | `kokoro,moss,zipvoice` | Public product model IDs; runtime providers are selected by Provider Policy and the deployment image. |
| `ANGEVOICE_DEFAULT_MODEL` | `kokoro` | Model selected in Studio on startup; loading is controlled by `ANGEVOICE_STARTUP_PRELOAD_ENABLED` |
| `ANGEVOICE_STARTUP_PRELOAD_ENABLED` | App and formal templates `false` | Preload a model through its worker during service startup; otherwise the first synthesis wakes it on demand |
| `ANGEVOICE_STARTUP_PRELOAD_MODEL` | `kokoro` | Model ID preloaded when startup preload is enabled |
| `ANGEVOICE_MODEL_UNLOAD_ON_SWITCH` | `true` | Unload old engine when switching |
| `ANGEVOICE_SAVE_OUTPUTS` | `true` | Save HTTP synthesis outputs in Docker profiles; code default is `false` outside Docker |
| `ANGEVOICE_MODELS_ROOT` | `/app/models` | Unified model root; Docker mounts host `./models` here |
| `KOKORO_MODEL_DIR` | `/app/models/models--hexgrad--Kokoro-82M-v1.1-zh` | Kokoro main model, config, and voices directory |
| `HF_HUB_CACHE` | `/app/models` | Hugging Face cache root; creates `models--hexgrad--Kokoro-82M-v1.1-zh` |
| `MODELSCOPE_CACHE` | `/app/models/modelscope-cache` | ModelScope cache directory |
| `ANGEVOICE_MODEL_SOURCE` | `auto` | Model download source: `auto` probes Hugging Face/ModelScope reachability first, then falls back to country detection; can be forced to `modelscope` / `huggingface` / `offline` |
| `KOKORO_MODELSCOPE_REPO` | `AI-ModelScope/Kokoro-82M-v1.1-zh` | ModelScope Kokoro repository for China-friendly auto downloads |
| `MOSS_MODELSCOPE_REPO` | `openmoss/MOSS-TTS-Nano-100M-ONNX` | ModelScope MOSS ONNX repository used as the default fallback download source |
| `MOSS_HF_REPO` | - | Optional Hugging Face MOSS ONNX repository; empty by default |
| `MOSS_MODEL_DIR` | `/app/models/MOSS-TTS-Nano-100M-ONNX` | MOSS ONNX model directory |
| `MOSS_EXECUTION_PROVIDER` | `cpu` | MOSS ONNX provider: `cpu` / `cuda` |
| `MOSS_CUDA_ENABLED` | `false` | Allow `MOSS-TTS-Nano` to request its CUDA provider; CPU/legacy-gpu keep it off and standard GPU enables it. |
| `MOSS_PROMPT_UPLOAD_MAX_BYTES` | `20971520` | MOSS clone reference-audio upload limit |
| `MOSS_SEGMENT_LENGTH` | `120` | MOSS-only stability-first segment length; reduces mixed-language drift, stutter and artifacts without changing Kokoro segmentation. |
| `MOSS_PROMPT_AUDIO_MAX_SECONDS` | `8` | Reference-audio trim duration |
| `MOSS_PROMPT_CACHE_MAX_ITEMS` | `8` | Encoded prompt-audio cache size |
| `MOSS_APPLY_ANGEVOICE_RULES` | `auto` | Text rules for MOSS: full Chinese normalization for Chinese-major text, conservative cleanup for mixed English/technical text |
| `MOSS_MIXED_ENGLISH_POLICY` | `translate` | Translate common mixed-English phrases into natural Chinese for MOSS; set `preserve` to keep original English |
| `MOSS_REALTIME_STREAMING_DECODE` | `true` | Enable official MOSS frame-level realtime decoding. It is enabled by default for low-latency streaming; disable it from the admin console only if a specific device shows boundary noise, memory pressure, or playback instability |
| `MOSS_OUTPUT_TARGET_PEAK` | `0.86` | MOSS target output peak, balancing dynamics and clipping protection |
| `MOSS_OUTPUT_GAIN` | `0.94` | Gentle MOSS postprocess gain to avoid overly quiet output while preserving dynamics |
| `MOSS_OUTPUT_DECLICK_ENABLED` | `true` | Remove isolated transient clicks/pops and reduce electrical artifacts |
| `MOSS_OUTPUT_EDGE_FADE_MS` | `1.5` | Short fade-in/out at MOSS segment edges to reduce splice pops without smearing consonants |
| `MOSS_MAX_SILENCE_MS` | `480` | Maximum continuous silence kept in polished MOSS output to reduce long perceived stalls |
| `MOSS_AUTO_FALLBACK_CPU` | `true` | Fall back to CPU when CUDA self-test fails |
| `MOSS_STREAM_PREBUFFER_SECONDS` | `3.0` | Browser prebuffer for MOSS streaming, reducing underflow on NAS/older GPUs |
| `MOSS_STREAM_QUEUE_MAX_ITEMS` | `8` | MOSS streaming queue depth to absorb short decode/browser/network jitter |
| `KOKORO_PROCESS_ISOLATION_ENABLED` | App default `false`; Docker/fnOS templates `true` | Run Kokoro in a killable worker so formal deployments can reclaim RAM/VRAM on release |
| `MOSS_PROCESS_ISOLATION_ENABLED` | App default `false`; Docker/fnOS templates `true` | Enable killable MOSS process isolation; formal deployment templates enable it so a timed-out worker can be terminated and rebuilt |
| `MOSS_PROCESS_ISOLATION_PROVIDERS` | App default `cuda`; Docker/fnOS templates `cpu,cuda` | Providers executed in an isolated worker process |
| `MOSS_PROCESS_KILL_GRACE_SECONDS` | `2` | Grace seconds before force-killing a timed-out worker |
| `ANGEVOICE_WEBSOCKET_STREAM_IDLE_TIMEOUT_SECONDS` | `120` | WebSocket streaming idle window while waiting for the next audio frame; prevents MOSS long-text first-frame or segment gaps from closing too early |
| `ANGEVOICE_ENGINE_PROCESS_STREAM_DRAIN_SECONDS` | `30` | Isolated-worker drain window after stream cancellation |
| `ANGEVOICE_ENGINE_PROCESS_STREAM_IDLE_TIMEOUT_SECONDS` | `120` | Isolated-worker streaming idle window while waiting for the next frame; avoids treating slow MOSS frames as worker hangs |
| `MOSS_VRAM_SNAPSHOT_TTL_SECONDS` | `10` | Cache CUDA VRAM snapshots to avoid frequent torch/nvidia-smi probes during streaming |
| `MOSS_QUALITY_GATE_ENABLED` | `true` | Reject silent, NaN/Inf, or heavily clipped MOSS self-test output |
| `ANGEVOICE_IDLE_TIMEOUT_SECONDS` | `600` | Auto-unload all loaded models after N idle seconds; 0 = disabled |
| `ANGEVOICE_IDLE_CHECK_INTERVAL` | `30` | Idle check interval (seconds) |
| `ANGEVOICE_RESTART_AFTER_IDLE_UNLOAD` | `false` | Optional full cleanup after idle unload; exits only after an idle unload succeeds and the service is fully idle. Requires Docker or a service manager to restart the process |
| `ANGEVOICE_RESTART_AFTER_IDLE_UNLOAD_DELAY_SECONDS` | `3` | Delay before exiting after idle unload; a new request during the delay cancels the exit |
| `ANGEVOICE_RESTART_AFTER_IDLE_UNLOAD_COOLDOWN_SECONDS` | `1800` | Cooldown to avoid repeated restarts in abnormal environments |
| `ANGEVOICE_RESTART_AFTER_IDLE_UNLOAD_EXIT_CODE` | `75` | Exit code used for intentional full-cleanup exits |
| `MOSS_STREAM_BUDGET_THRESHOLD_LOW` | `0.25` | Audio lead low threshold in seconds; below this decode 1 frame for faster first audio |
| `MOSS_STREAM_BUDGET_THRESHOLD_MID` | `0.65` | Audio lead mid threshold; below this decode 2 frames |
| `MOSS_STREAM_BUDGET_THRESHOLD_HIGH` | `1.20` | Audio lead high threshold; below this decode 4 frames, above this decode 8 frames |
| `MOSS_STREAM_CHUNK_MIN_FLOOR` | `0.10` | Minimum stream chunk floor (seconds) to avoid tiny choppy fragments |
| `KOKORO_TRUST_PROXY_HEADERS` | `false` | Do not trust `X-Forwarded-For` by default; enable only behind a trusted reverse proxy |
| `KOKORO_PUBLIC_STATUS_ENDPOINTS` | `true` | Keep `/v1/models`, `/v1/models/current`, and `/v1/audio/voices` public; set false to require Bearer auth for them while leaving `/health` public |

## Security notes

- Docker/fnOS templates default to `KOKORO_API_KEY=auto` and enable basic HTTP/WebSocket entry guards. Leaving the API key empty remains supported only for trusted local/source deployments; do not expose that mode publicly.
- Docker templates provide `admin / admin123` for first entry so users can obtain the API key. Change the credentials before public exposure; changed passwords are stored only as hashes. Restrict `/admin` at the reverse proxy.
- `.pt` voice upload is disabled by default. Only upload trusted files.

⚠️ **Security Warning**: Enabling `KOKORO_VOICE_UPLOAD_ENABLED` on public-facing servers is **strongly discouraged**.
Only upload `.pt` files you generated yourself or from fully trusted sources.
If upload must be enabled, restrict to internal network admin endpoints with reverse-proxy IP whitelisting.
`.pt` files use PyTorch serialization which can theoretically execute arbitrary code.
- Do not expose `/admin/*` directly to the public internet.

See [`docs/SECURITY.md`](docs/SECURITY.md).

## Known limitations

- AngeVoice does not train a new model; quality, license, and language capability follow upstream models.
- Kokoro, MOSS-TTS-Nano and ZipVoice Docker/fnOS templates enable killable isolated workers by default. Startup preload is off, so the first request shows a wake/load state. If isolation is disabled, VRAM may be released on a best-effort basis but host RAM is not guaranteed to return to a cold-start baseline.
- The optional full cleanup after idle unload is disabled by default. It only exits after an idle unload succeeds; use it with `restart: unless-stopped`, `restart: always`, or an equivalent service manager policy.
- MOSS runtime provider status is reported separately from its product name. Legacy request IDs `moss-nano-cpu` / `moss-nano-cuda` remain accepted only for compatibility. Keep the standard `gpu` path evidence-based on the target host before long-running service.
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
- [Legacy GPU Deployment](docker/legacy-gpu/README.md)

## License and acknowledgements

AngeVoice is released under the [Apache License 2.0](LICENSE); see [NOTICE](NOTICE) for the project copyright notice. Its core model/runtime integrations are built on [Kokoro](https://huggingface.co/hexgrad/Kokoro-82M), [MOSS-TTS-Nano](https://github.com/OpenMOSS/MOSS-TTS-Nano), and [ZipVoice](https://github.com/k2-fsa/ZipVoice), each used under its upstream Apache License 2.0 terms. Other dependencies and runtime-downloaded assets remain subject to their own licenses.

See [NOTICE](NOTICE), [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), and [ACKNOWLEDGEMENTS.md](ACKNOWLEDGEMENTS.md).
