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
- `voice_clone`: upload a short reference audio file through `/api/tts` or the WebSocket first message.

All model adapters use the shared AngeVoice text-normalization path by default.
That means Chinese punctuation insertion, lightweight semantic matching,
clock-time reading, and common polyphone overrides are applied before Kokoro,
MOSS, or later engines receive text. Set `MOSS_APPLY_ANGEVOICE_RULES=false`
only when comparing raw upstream MOSS behavior.

## APIs

Full endpoint matrix and copy-paste examples are maintained in
[API Reference](API_REFERENCE.md). The snippets below focus on model runtime
operations.

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

For WebSocket streaming, put the reference audio into the first JSON message as
base64 or a data URL. The server writes it to a temporary file, applies the same
size/suffix checks, trims it for inference, and removes the upload after the
request:

```json
{
  "model": "moss-nano-cpu",
  "text": "这是参考音频克隆的流式测试。",
  "voice": "Junhao",
  "format": "pcm_s16le",
  "prompt_audio": {
    "filename": "reference.wav",
    "data": "<base64>"
  }
}
```

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
| `MOSS_CUDA_MEMORY_LIMIT_MB` | `0` | Optional ORT CUDA arena cap; `0` leaves VRAM unrestricted for general GPU compatibility |
| `MOSS_CPU_THREADS` | `4` | ONNX Runtime intra-op threads |
| `MOSS_DEFAULT_VOICE` | `Junhao` | Built-in MOSS voice preset |
| `MOSS_SAMPLE_MODE` | `fixed` | MOSS sampling mode; `greedy` is more stable but flatter |
| `MOSS_SEED` | `1234` | Reset RNG per request to reduce long-text voice drift; `-1` disables |
| `MOSS_STREAM_CHUNK_SECONDS` | `0.42` | MOSS WebSocket chunk duration; balances first audio and smoothness |
| `MOSS_STREAM_QUEUE_MAX_ITEMS` | `8` | Streaming queue backpressure limit |
| `MOSS_PROMPT_AUDIO_PATH` | - | Optional reference audio for voice cloning |
| `MOSS_PROMPT_UPLOAD_MAX_BYTES` | `20971520` | `/api/tts` reference-audio upload limit |
| `MOSS_PROMPT_AUDIO_MAX_SECONDS` | `10` | Trim uploaded/reference audio before codec encoding |
| `MOSS_PROMPT_CACHE_MAX_ITEMS` | `8` | LRU cache size for encoded prompt audio codes |
| `MOSS_APPLY_ANGEVOICE_RULES` | `true` | Apply AngeVoice Chinese rules before MOSS inference |
| `MOSS_AUTO_FALLBACK_CPU` | `true` | Fall back to CPU if CUDA load/self-test fails |
| `MOSS_CUDA_SELF_TEST_ENABLED` | `true` | Warm up CUDA provider before serving |
| `MOSS_QUALITY_GATE_ENABLED` | `true` | Reject silent/clipped/invalid test output |
| `MOSS_OUTPUT_PEAK_NORMALIZE_ENABLED` | `true` | Scale MOSS output down when it exceeds the target peak |
| `MOSS_OUTPUT_TARGET_PEAK` | `0.78` | Softer MOSS output peak target to reduce clipping and small-speaker bursts |
| `MOSS_OUTPUT_GAIN` | `0.90` | Slight pre-normalization attenuation to preserve dynamics and reduce distortion |
| `MOSS_OUTPUT_DECLICK_ENABLED` | `true` | Repair isolated impulse spikes before encoding |
| `MOSS_OUTPUT_EDGE_FADE_MS` | `2` | Short fade-in/out for MOSS segment boundaries |
| `MOSS_REALTIME_STREAMING_DECODE` | `true` | Low-latency default with stateful smoothing. Disable only when quality-first full-chunk generation is preferred |


## MOSS 进程级隔离

MOSS 进程级隔离默认关闭，默认路径为同进程推理；MOSS 逐帧实时解码默认关闭，优先保证 Web/小智播放质量。
需要排查 CUDA/ONNX Runtime 底层卡死时，可以手动开启隔离；开启后主服务进程会把匹配 provider 的请求发给独立 worker 子进程，worker 长时间无事件或超时时会被 terminate/kill，并在下次请求重建 runtime。

默认配置：

```env
MOSS_PROCESS_ISOLATION_ENABLED=false
MOSS_PROCESS_ISOLATION_PROVIDERS=cuda
MOSS_PROCESS_KILL_GRACE_SECONDS=2
```

默认情况下 CPU/CUDA 都不走进程隔离；如需只隔离 CUDA，可设置 `MOSS_PROCESS_ISOLATION_ENABLED=true` 且保留 `MOSS_PROCESS_ISOLATION_PROVIDERS=cuda`。如需对 CPU 也隔离，可设置 `MOSS_PROCESS_ISOLATION_PROVIDERS=cpu,cuda`。

## Runtime Tuning

MOSS-TTS-Nano is small, but the official runtime still spends noticeable time
in text generation and codec encode/decode. AngeVoice keeps one executor per
loaded MOSS engine, serializes access to the mutable official runtime, and
caches encoded prompt-audio codes. This avoids per-request thread-pool churn and
prevents multiple requests from mutating the runtime manifest or codec streaming
session at the same time.

For NAS/low-power deployments, keep:

```bash
KOKORO_MAX_CONCURRENT_REQUESTS=1
MOSS_CPU_THREADS=2
MOSS_PROMPT_AUDIO_MAX_SECONDS=8
MOSS_PROMPT_CACHE_MAX_ITEMS=6
MOSS_STREAM_CHUNK_SECONDS=0.42
MOSS_OUTPUT_PEAK_NORMALIZE_ENABLED=true
MOSS_REALTIME_STREAMING_DECODE=true
MOSS_OUTPUT_TARGET_PEAK=0.78
MOSS_OUTPUT_GAIN=0.90
MOSS_OUTPUT_DECLICK_ENABLED=true
MOSS_OUTPUT_EDGE_FADE_MS=2
```

For modern GPUs with 8 GB VRAM, keep reference audio short. Long clone samples
can make the codec encoder allocate multi-GB buffers even though the acoustic
model itself is small.

If CUDA session creation fails with CUBLAS or BFC arena allocation errors on a
tight 8 GB card, first stop other GPU containers or switch idle AngeVoice
models back to Kokoro/CPU. As a last resort, set `MOSS_CUDA_MEMORY_LIMIT_MB`
manually, for example `4096` on a Tesla P4. The default stays `0` so larger GPUs
can use their full VRAM.

MOSS WebSocket streaming defaults to a quality-first path: AngeVoice asks the
official runtime for a complete high-quality chunk, then bounds the WebSocket
frame size before sending it to the browser or Xiaozhi.  If you need lower
first-packet latency and can tolerate more chunk-boundary risk, set
`MOSS_REALTIME_STREAMING_DECODE=true` to use OpenMOSS `generate_audio_frames`
and codec streaming decode. Kokoro exposes segment-level generation through its
official pipeline, so AngeVoice bounds the WebSocket frame size after each
Kokoro segment is generated.

## Docker Notes

Docker profiles preinstall the matching MOSS runtime but still start with
`ANGEVOICE_DEFAULT_MODEL=kokoro`:

- CPU image: `kokoro,moss-nano-cpu`; `MOSS_CUDA_ENABLED=false`.
- Modern GPU image: `kokoro,moss-nano-cpu,moss-nano-cuda`;
  `MOSS_EXECUTION_PROVIDER=cuda`.
- Legacy GPU image (老架构GPU 镜像): preinstalls CUDA 11.8 compatible MOSS GPU dependencies
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


### MOSS 模块拆分

`moss_engine.py` 保留对外兼容的 `MossNanoEngine`，但运行时加载、自检、文本分段、prompt audio 缓存、流式预算和音频后处理已拆到 `src/kokoro_tts/moss/` 子包，便于后续单测和定位失真/卡顿问题。
