# Multi-Model Runtime / 多模型运行时

AngeVoice keeps Kokoro as the default lightweight engine and adds a model
manager so optional engines can be loaded, switched, and unloaded at runtime.
The first optional engine is MOSS-TTS-Nano through the official OpenMOSS ONNX
runtime.

## Model IDs

| ID | Purpose | Default provider |
|---|---|---|
| `kokoro` | Kokoro v1.1 Chinese engine | PyTorch CPU/CUDA |
| `moss-nano-cpu` | MOSS-TTS-Nano ONNX on CPU | ONNX Runtime CPU |
| `moss-nano-cuda` | MOSS-TTS-Nano ONNX on CUDA | ONNX Runtime CUDA, experimental |

Aliases such as `moss-nano` and `moss` resolve to `MOSS_EXECUTION_PROVIDER`.
When `MOSS_CUDA_ENABLED=false`, CUDA aliases are hidden and generic MOSS
aliases resolve to the CPU model.

MOSS models expose two modes:

- `preset_voice`: use built-in MOSS voices such as `Junhao`.
- `voice_clone`: upload a short reference audio file through `/api/tts`.

All model adapters use the shared AngeVoice text-normalization path by default.
That means Chinese punctuation insertion, lightweight semantic matching,
clock-time reading, and common polyphone overrides are applied before Kokoro,
MOSS, or later engines receive text. Set `MOSS_APPLY_ANGEVOICE_RULES=false`
only when comparing raw upstream MOSS behavior.

## APIs

```bash
curl http://localhost:8000/v1/models
curl http://localhost:8000/v1/models/current

curl -X POST http://localhost:8000/v1/models/switch \
  -H "Content-Type: application/json" \
  -d '{"model":"moss-nano-cpu","unload_previous":true}'
```

Speech requests can select a model directly:

```bash
curl -X POST http://localhost:8000/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"model":"moss-nano-cpu","input":"你好世界","voice":"Junhao","response_format":"wav"}' \
  --output output.wav
```

Reference-audio cloning is available on `/api/tts` with multipart form data:

```bash
curl -X POST http://localhost:8000/api/tts \
  -F model=moss-nano-cpu \
  -F text="这是参考音频克隆测试。" \
  -F voice=Junhao \
  -F response_format=wav \
  -F prompt_audio=@reference.wav \
  --output clone.wav
```

The request cache includes a reference-audio fingerprint, so different prompt
audio files cannot collide with each other. Uploading `prompt_audio` to a model
without `voice_clone` returns 400.

## Environment

| Variable | Default | Notes |
|---|---|---|
| `ANGEVOICE_ENABLED_MODELS` | `kokoro` | Comma-separated model IDs |
| `ANGEVOICE_DEFAULT_MODEL` | `kokoro` | Loaded on startup |
| `ANGEVOICE_MODEL_SWITCH_ENABLED` | `true` | Enables `/v1/models/*` management APIs |
| `ANGEVOICE_MODEL_UNLOAD_ON_SWITCH` | `true` | Unload the previous engine when switching |
| `ANGEVOICE_SAVE_OUTPUTS` | `false` | Persist HTTP synthesis outputs |
| `ANGEVOICE_OUTPUT_DIR` | `/app/outputs` | Output directory |
| `ANGEVOICE_OUTPUT_MAX_FILES` | `1000` | Max retained output files; `0` disables pruning |
| `MOSS_TTS_NANO_PATH` | - | Path to a local clone of `OpenMOSS/MOSS-TTS-Nano` |
| `MOSS_MODEL_DIR` | - | Optional ONNX asset directory; Docker uses `/opt/MOSS-TTS-Nano/models` |
| `MOSS_EXECUTION_PROVIDER` | `cpu` | `cpu` or `cuda` |
| `MOSS_CUDA_ENABLED` | `true` | Allows registering `moss-nano-cuda`; CPU/legacy Compose disable it |
| `MOSS_CPU_THREADS` | `4` | ONNX Runtime intra-op threads |
| `MOSS_DEFAULT_VOICE` | `Junhao` | Built-in MOSS voice preset |
| `MOSS_PROMPT_AUDIO_PATH` | - | Optional reference audio for voice cloning |
| `MOSS_PROMPT_UPLOAD_MAX_BYTES` | `20971520` | `/api/tts` reference-audio upload limit |
| `MOSS_APPLY_ANGEVOICE_RULES` | `true` | Apply AngeVoice Chinese rules before MOSS inference |
| `MOSS_AUTO_FALLBACK_CPU` | `true` | Fall back to CPU if CUDA load/self-test fails |
| `MOSS_CUDA_SELF_TEST_ENABLED` | `true` | Warm up CUDA provider before serving |
| `MOSS_QUALITY_GATE_ENABLED` | `true` | Reject silent/clipped/invalid test output |

## Docker Notes

Docker profiles preinstall the matching MOSS runtime but still start with
`ANGEVOICE_DEFAULT_MODEL=kokoro`:

- CPU image: `kokoro,moss-nano-cpu`; `MOSS_CUDA_ENABLED=false`.
- Modern GPU image: `kokoro,moss-nano-cpu,moss-nano-cuda`;
  `MOSS_EXECUTION_PROVIDER=cuda`.
- Legacy GPU image: preinstalls CUDA 11.8 compatible MOSS GPU dependencies
  from the official ONNX Runtime CUDA 11 feed, but exposes only
  `kokoro,moss-nano-cpu` until the user explicitly enables `moss-nano-cuda`
  and `MOSS_CUDA_ENABLED=true`.

Keep `../../moss_models:/opt/MOSS-TTS-Nano/models` mounted to persist
downloaded ONNX assets, and keep `../../outputs:/app/outputs` mounted when
`ANGEVOICE_SAVE_OUTPUTS=true`.

`moss-nano-cuda` depends on a compatible ONNX Runtime CUDA/cuDNN stack and must
pass the built-in self-test before it is considered usable.
ONNX Runtime's CUDA compatibility matrix is the source of truth for CUDA/cuDNN
wheel selection: https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html

Tesla P4 validation result: CUDA inference passed in Docker with
`onnxruntime-gpu==1.20.2`, `nvidia-cudnn-cu12==9.1.0.70`, CUDA 12.1, and the
official MOSS runtime. Without cuDNN 9, ONNX Runtime advertises
`CUDAExecutionProvider` but creates CPU sessions, which AngeVoice rejects and
falls back from.

## Non-Docker Setup

For development outside Docker, keep the official MOSS repository as a separate
checkout and point AngeVoice at it:

```bash
git clone https://github.com/OpenMOSS/MOSS-TTS-Nano.git
pip install -e ".[moss]"
export MOSS_TTS_NANO_PATH=/path/to/MOSS-TTS-Nano
export ANGEVOICE_ENABLED_MODELS=kokoro,moss-nano-cpu
```

Use `.[moss-gpu]` only after confirming the target CUDA/cuDNN stack matches the
selected `onnxruntime-gpu` wheel.
