# AngeVoice 服务画像说明 / Service Profiles

AngeVoice 主要维护三类部署画像：`cpu`、推荐的通用 `gpu`、以及兼容模式的 `legacy-gpu`。三者共享同一套 API、Studio Web UI、中文规则、缓存、统计和安全校验，只在运行时参数、CUDA 基础镜像和端口默认值上不同。

有 NVIDIA GPU 时请先尝试 `docker/gpu`。`legacy-gpu` 是 CUDA 11.8 兼容模式画像，仅在 `gpu` 镜像无法启动、CUDA/cuDNN 不兼容或旧驱动环境不稳定时使用，不保证性能优于 `gpu`。

## 1. 通用服务版

适合大多数 CPU/GPU/云服务器环境，默认追求稳定、兼容和易部署。所有画像默认启动模型仍是 Kokoro，MOSS 与 ZipVoice 只在用户通过 Web UI/API 切换时加载。标准 `gpu` 画像对 ZipVoice 提供 CUDA 请求与稳定 CPU 回退；Tesla P4 已支持 CUDA 生成，实际表现取决于目标设备与驱动环境。

推荐配置：

```bash
KOKORO_WORKERS=1
KOKORO_MAX_CONCURRENT_REQUESTS=1
KOKORO_CACHE_ENABLED=true
KOKORO_CACHE_MAX_ITEMS=64
KOKORO_STREAM_BINARY_ENABLED=true
KOKORO_STREAM_CHUNK_SECONDS=0.55
KOKORO_REQUEST_TIMEOUT_SECONDS=300
ANGEVOICE_ENABLED_MODELS=kokoro
ANGEVOICE_MODEL_UNLOAD_ON_SWITCH=true
```

能力：

- OpenAI 风格 `/v1/audio/speech`
- `/api/tts` 旧版接口
- `/ws/v1/tts` 小包流式接口
- Studio Web UI，支持亮/暗主题、API Key 设置、音色筛选、收藏和可折叠统计卡片
- 中文自动断句、多音字和轻量分词规则
- `/stats` 服务统计
- `/requests` 最近请求状态
- 内存 LRU 音频缓存
- HTTP 合成结果可选持久化到 `/app/outputs`
- 请求 ID 响应头 `X-Request-ID`
- WebSocket JSON + 可选 binary 音频帧
- 可选多模型运行时：Docker 画像预装匹配的 MOSS runtime，可通过 Studio 或 `/v1/models/switch` 切换，MOSS 克隆模式会显示参考音频上传控件

## 2. legacy-gpu 兼容模式版

适合通用 `gpu` 画像无法启动、CUDA/cuDNN 不兼容、旧驱动、NAS 或低功耗主机。它是兼容方案，不是性能最优保证。

推荐配置：

```bash
KOKORO_WORKERS=1
KOKORO_MAX_CONCURRENT_REQUESTS=1
KOKORO_CACHE_ENABLED=true
KOKORO_CACHE_MAX_ITEMS=64
KOKORO_STREAM_BINARY_ENABLED=true
KOKORO_STREAM_CHUNK_SECONDS=0.55
KOKORO_REQUEST_TIMEOUT_SECONDS=600
KOKORO_SEGMENT_LENGTH=100
ANGEVOICE_ENABLED_MODELS=kokoro,moss,zipvoice
MOSS_EXECUTION_PROVIDER=cpu
MOSS_CUDA_ENABLED=false
MOSS_SEGMENT_LENGTH=120
MOSS_REALTIME_STREAMING_DECODE=true
MOSS_PROMPT_AUDIO_MAX_SECONDS=8
MOSS_PROMPT_CACHE_MAX_ITEMS=8
MOSS_SAMPLE_MODE=fixed
MOSS_SEED=1234
MOSS_STREAM_CHUNK_SECONDS=0.40
MOSS_STREAM_QUEUE_MAX_ITEMS=8
MOSS_OUTPUT_PEAK_NORMALIZE_ENABLED=true
MOSS_OUTPUT_TARGET_PEAK=0.86
```

建议：

- 优先使用稳定的 PyTorch/CUDA 组合，不强求最新 CUDA。
- 不建议多 worker 同时加载 GPU 模型。
- 如果确实设置 `KOKORO_WORKERS>1`，AngeVoice 会使用 Uvicorn factory/import-string 模式启动；每个 worker 仍会加载独立模型和缓存。
- 遇到音频噪声、爆音或推理异常时，优先关闭半精度、TensorRT、flash attention 等加速。
- Kokoro 保持自己的分段；MOSS 使用独立的 `MOSS_SEGMENT_LENGTH=120`，优先减少中英文混合尾部漂移、卡顿和失真。
- WebSocket 默认 binary 音频，兼容旧客户端时可改回 JSON/base64。
- MOSS-TTS-Nano 在 legacy-gpu 画像中默认只开放 CPU ONNX；镜像预装 CUDA 11.8 兼容的 MOSS GPU 依赖，如需测试请使用 `docker-compose.moss-cuda.yml`。
- ZipVoice 在 legacy-gpu 中固定使用ONNX INT8 CPU；该画像仅作为标准 `gpu` 无法稳定运行时的兼容。

## 3. MOSS-TTS-Nano 可选画像

适合希望在同一个 AngeVoice 服务里切换 Kokoro 与 MOSS 的部署。Docker 画像已经预装对应 runtime，默认启动仍是 Kokoro，MOSS 模型资产会在首次加载时下载到持久化目录。

推荐配置：

```bash
# CPU / 老架构GPU
ANGEVOICE_ENABLED_MODELS=kokoro,moss,zipvoice
ANGEVOICE_DEFAULT_MODEL=kokoro
MOSS_EXECUTION_PROVIDER=cpu
MOSS_CUDA_ENABLED=false
MOSS_CPU_THREADS=2
MOSS_MODEL_DIR=/app/models/MOSS-TTS-Nano-100M-ONNX
MOSS_PROMPT_UPLOAD_MAX_BYTES=20971520
MOSS_PROMPT_AUDIO_MAX_SECONDS=8
MOSS_PROMPT_CACHE_MAX_ITEMS=8
MOSS_SAMPLE_MODE=fixed
MOSS_SEED=1234
MOSS_STREAM_CHUNK_SECONDS=0.40
MOSS_STREAM_QUEUE_MAX_ITEMS=8
MOSS_AUTO_FALLBACK_CPU=true
MOSS_QUALITY_GATE_ENABLED=true
MOSS_OUTPUT_PEAK_NORMALIZE_ENABLED=true
MOSS_OUTPUT_TARGET_PEAK=0.86
```

通用 GPU 画像默认：

```bash
ANGEVOICE_ENABLED_MODELS=kokoro,moss,zipvoice
ANGEVOICE_DEFAULT_MODEL=kokoro
MOSS_EXECUTION_PROVIDER=cuda
MOSS_CUDA_ENABLED=true
MOSS_CUDA_MEMORY_LIMIT_MB=0
ZIPVOICE_EXECUTION_PROVIDER=cuda
ZIPVOICE_CUDA_ENABLED=true
ZIPVOICE_AUTO_FALLBACK_CPU=true
ZIPVOICE_CUDA_MAX_DURATION=36
```

Tesla P4 Docker 回传已确认标准 GPU 画像能运行 Kokoro、MOSS-TTS-Nano 与 ZipVoice CUDA，因此标准 `gpu` 为推荐路径；ZipVoice 仍必须使用相同 Profile/文本与 CPU 基线做性能对比，并验证长文本、取消、显存/RSS 与 CPU 回退。如果缺 cuDNN 9，ONNX Runtime 会退成 CPU session，AngeVoice 会拒绝该 CUDA 加载并回退 CPU。长期运行前仍要人工试听，确认无静音、爆音、失真或 clipping。`MOSS_CUDA_MEMORY_LIMIT_MB` 默认保持 `0`，不限制大显存用户；只有 8GB 小显存排障时才建议手动设置。

MOSS 克隆参考音频会被裁剪到 `MOSS_PROMPT_AUDIO_MAX_SECONDS`，并缓存编码后的 prompt audio codes。这样可以降低 clone 模式在 8GB 显存和低功耗 CPU 上的重复开销；如果仍然出现 OOM 或爆音，优先缩短参考音频而不是提高并发。

WebSocket 输出会按固定时长切成小音频包。Kokoro 仍按官方 pipeline 段落推理；MOSS 默认启用 `MOSS_REALTIME_STREAMING_DECODE=true` 以降低首包等待。如果逐帧模式出现电流音、卡顿或边界噪声，可改为 `false`。长文本建议使用 `MOSS_SEGMENT_LENGTH=120` 或更高，减少中英文混合尾部漂移、卡顿和失真。

持久化要求：

```yaml
volumes:
  - ../../credentials:/app/credentials
  - ../../config:/app/config
  - ../../models:/app/models
  - ../../prompts:/app/prompts
  - ../../outputs:/app/outputs
  - ../../logs:/app/logs
```

## API 快速检查

完整接口矩阵和 MOSS 克隆调用示例见 [API 参考](API_REFERENCE.md)。不同画像只需要替换端口：CPU 默认 `8100`，GPU 默认 `8101`，老架构GPU 默认 `8102`。

```bash
curl http://localhost:8000/health
curl http://localhost:8000/stats
curl http://localhost:8000/requests
curl http://localhost:8000/v1/models
```

```bash
curl -X POST http://localhost:8000/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"model":"kokoro","input":"你好世界","voice":"zm_010","response_format":"wav"}' \
  --output output.wav
```

启用认证时：

```bash
curl http://localhost:8000/stats \
  -H "Authorization: Bearer YOUR_GENERATED_TOKEN"
```

## 长文本自然语音预设（MOSS）

从 2.6.5.3 起，MOSS 默认启用轻量自然切片、静音压缩、短 crossfade 和流式预缓冲。目标是减少长文本中的卡顿、重复读、变调和异常长静音，同时保持 NAS/老显卡用户的稳定性。

### 推荐默认

```env
MOSS_SEGMENT_LENGTH=120
MOSS_MIXED_ENGLISH_POLICY=translate
MOSS_VOICE_CLONE_MAX_TEXT_TOKENS=56
MOSS_MAX_NEW_FRAMES=320
MOSS_STREAM_CHUNK_SECONDS=0.40
MOSS_STREAM_QUEUE_MAX_ITEMS=8
MOSS_STREAM_PREBUFFER_SECONDS=0.75
MOSS_AUDIO_POLISH_ENABLED=true
MOSS_MAX_SILENCE_MS=480
MOSS_CROSSFADE_MS=12
MOSS_RUNTIME_PAUSE_MAX_MS=350
```

### 中文小说/旁白

```env
MOSS_SEGMENT_LENGTH=280
MOSS_VOICE_CLONE_MAX_TEXT_TOKENS=56
MOSS_MAX_NEW_FRAMES=460
MOSS_MAX_SILENCE_MS=480
MOSS_SEGMENT_PAUSE_MS=100
```

### 低延迟对话

```env
MOSS_SEGMENT_LENGTH=120
MOSS_STREAM_CHUNK_SECONDS=0.35
MOSS_STREAM_PREBUFFER_SECONDS=0.55
MOSS_CROSSFADE_MS=20
```

详细解释见 `docs/MOSS_AUDIO_QUALITY.md`。
