# AngeVoice 服务画像说明 / Service Profiles

AngeVoice 按通用服务版和老显卡/保守兼容版两个部署画像维护。两者共享同一套 API、Studio Web UI、中文规则、缓存、统计和安全校验，只在运行时参数、CUDA 基础镜像和端口默认值上有所不同。

## 1. 通用服务版

适合大多数 CPU/GPU/云服务器环境，默认追求稳定、兼容和易部署。所有画像默认启动模型仍是 Kokoro，MOSS 只在用户通过 Web UI/API 切换时加载。

推荐配置：

```bash
KOKORO_WORKERS=1
KOKORO_MAX_CONCURRENT_REQUESTS=1
KOKORO_CACHE_ENABLED=true
KOKORO_CACHE_MAX_ITEMS=128
KOKORO_STREAM_BINARY_ENABLED=true
KOKORO_REQUEST_TIMEOUT_SECONDS=300
ANGEVOICE_ENABLED_MODELS=kokoro
ANGEVOICE_MODEL_UNLOAD_ON_SWITCH=true
```

能力：

- OpenAI 风格 `/v1/audio/speech`
- `/api/tts` 旧版接口
- `/ws/v1/tts` 逐段流式接口
- Studio Web UI，支持亮/暗主题、API Key 设置、音色筛选、收藏和可折叠统计卡片
- 中文自动断句、多音字和轻量分词规则
- `/stats` 服务统计
- `/requests` 最近请求状态
- 内存 LRU 音频缓存
- HTTP 合成结果可选持久化到 `/app/outputs`
- 请求 ID 响应头 `X-Request-ID`
- WebSocket JSON + 可选 binary 音频帧
- 可选多模型运行时：Docker 画像预装匹配的 MOSS runtime，可通过 Studio 或 `/v1/models/switch` 切换，MOSS 克隆模式会显示参考音频上传控件

## 2. 老显卡/保守兼容版

适合旧驱动、旧 GPU、NAS、低功耗主机或不希望使用激进 GPU 运行时的环境。

推荐配置：

```bash
KOKORO_WORKERS=1
KOKORO_MAX_CONCURRENT_REQUESTS=1
KOKORO_CACHE_ENABLED=true
KOKORO_CACHE_MAX_ITEMS=64
KOKORO_STREAM_BINARY_ENABLED=false
KOKORO_REQUEST_TIMEOUT_SECONDS=600
KOKORO_SEGMENT_LENGTH=80
ANGEVOICE_ENABLED_MODELS=kokoro,moss-nano-cpu
MOSS_EXECUTION_PROVIDER=cpu
MOSS_CUDA_ENABLED=false
ANGEVOICE_SAVE_OUTPUTS=true
```

建议：

- 优先使用稳定的 PyTorch/CUDA 组合，不强求最新 CUDA。
- 不建议多 worker 同时加载 GPU 模型。
- 如果确实设置 `KOKORO_WORKERS>1`，AngeVoice 会使用 Uvicorn factory/import-string 模式启动；每个 worker 仍会加载独立模型和缓存。
- 遇到音频噪声、爆音或推理异常时，优先关闭半精度、TensorRT、flash attention 等加速。
- 长文本建议降低 `KOKORO_SEGMENT_LENGTH`，减少单段失败概率。
- WebSocket 建议先使用 JSON base64 模式，确认稳定后再开启 binary 模式。
- MOSS-TTS-Nano 在 legacy GPU 画像中默认只开放 CPU ONNX；镜像已通过 ONNX Runtime CUDA 11 feed 预装 CUDA 11.8 兼容的 MOSS GPU 依赖，`moss-nano-cuda` 需要用户手动加入并打开 `MOSS_CUDA_ENABLED=true` 后才会出现在 UI。

## 3. MOSS-TTS-Nano 可选画像

适合希望在同一个 AngeVoice 服务里切换 Kokoro 与 MOSS 的部署。Docker 画像已经预装对应 runtime，默认启动仍是 Kokoro，MOSS 模型资产会在首次加载时下载到持久化目录。

推荐配置：

```bash
# CPU / legacy GPU
ANGEVOICE_ENABLED_MODELS=kokoro,moss-nano-cpu
ANGEVOICE_DEFAULT_MODEL=kokoro
MOSS_EXECUTION_PROVIDER=cpu
MOSS_CUDA_ENABLED=false
MOSS_CPU_THREADS=2
MOSS_MODEL_DIR=/opt/MOSS-TTS-Nano/models
MOSS_PROMPT_UPLOAD_MAX_BYTES=20971520
MOSS_AUTO_FALLBACK_CPU=true
MOSS_QUALITY_GATE_ENABLED=true
```

通用 GPU 画像默认：

```bash
ANGEVOICE_ENABLED_MODELS=kokoro,moss-nano-cpu,moss-nano-cuda
ANGEVOICE_DEFAULT_MODEL=kokoro
MOSS_EXECUTION_PROVIDER=cuda
MOSS_CUDA_ENABLED=true
```

Tesla P4 已用 Docker 探针验证可在通用 GPU 画像的 `onnxruntime-gpu==1.20.2` + `nvidia-cudnn-cu12==9.1.0.70` 下跑通 MOSS CUDA 推理；如果缺 cuDNN 9，ONNX Runtime 会退成 CPU session，AngeVoice 会拒绝该 CUDA 加载并回退 CPU。长期运行前仍要人工试听，确认无静音、爆音、失真或 clipping。

持久化建议：

```yaml
volumes:
  - ../../moss_models:/opt/MOSS-TTS-Nano/models
  - ../../outputs:/app/outputs
```

## API 快速检查

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
