# AngeVoice 排障手册 / Troubleshooting

完整接口地址、字段和 MOSS 克隆示例见 [API 参考](API_REFERENCE.md)。普通用户也可以直接打开服务内置页面：

```text
http://localhost:8000/api-docs
```

Docker 端口按部署画像替换：CPU 默认 `8100`，GPU 默认 `8101`，老架构 GPU 默认 `8102`，pip 开发默认 `8000`。

## 1. 服务启动后一直下载模型

原因：本地模型文件不存在，或 Git LFS 只下载了指针文件。

检查：

```bash
ls -lh models/
ls -lh models/voices/
head -5 models/kokoro-v1_1-zh.pth
```

如果看到 `version https://git-lfs.github.com/spec/v1`，说明它只是 LFS 指针，不是真实权重。

修复：

```bash
pip install huggingface_hub
huggingface-cli download hexgrad/Kokoro-82M-v1.1-zh \
  --local-dir models/ \
  --include "config.json" "kokoro-v1_1-zh.pth" "voices/*.pt"
```

## 2. Docker 能启动但 `/health` 很久才 ok

首次加载模型会下载或初始化权重，GPU 机器也需要 CUDA 初始化。建议：

```bash
docker logs -f angevoice-gpu
curl http://127.0.0.1:8101/health
```

确保 Compose 中 Hugging Face cache 已挂载：

```yaml
- ../../hf_cache:/root/.cache/huggingface
```

## 3. GPU 显存占用过高或 OOM

建议：

```bash
KOKORO_WORKERS=1
KOKORO_MAX_CONCURRENT_REQUESTS=1
KOKORO_BATCH_CONCURRENCY=1
```

Uvicorn 多 worker 会让每个 worker 加载一份模型，GPU 场景通常不要开多个 worker。

## 4. MOSS 模型不可选或切换失败

先看模型列表：

```bash
curl http://localhost:8000/v1/models
```

如果 `moss-nano-cpu` / `moss-nano-cuda` 显示 `available=false`，通常是官方 OpenMOSS runtime 没有安装、`MOSS_TTS_NANO_PATH` 指向错误，或当前镜像不是 v2.6 之后的 MOSS 预装画像。

检查：

```bash
docker compose config | grep -E "ANGEVOICE_ENABLED_MODELS|MOSS_CUDA_ENABLED|MOSS_EXECUTION_PROVIDER"
docker exec -it angevoice-gpu python3 - <<'PY'
import importlib.util
print(importlib.util.find_spec("onnx_tts_runtime"))
PY
```

CPU 镜像默认不注册 `moss-nano-cuda`；老架构 GPU 画像虽然预装了 MOSS GPU 依赖，但默认也会通过 `MOSS_CUDA_ENABLED=false` 隐藏 CUDA MOSS。

如果 CUDA 模式失败但 CPU 可用，保持：

```bash
MOSS_AUTO_FALLBACK_CPU=true
MOSS_QUALITY_GATE_ENABLED=true
```

老架构 GPU 要试 CUDA MOSS 时，需要同时设置：

```bash
ANGEVOICE_ENABLED_MODELS=kokoro,moss-nano-cpu,moss-nano-cuda
MOSS_CUDA_ENABLED=true
MOSS_EXECUTION_PROVIDER=cuda
```

Tesla P4 实测可跑 MOSS CUDA，但 GPU 镜像必须带 cuDNN 9。推荐组合：

```text
onnxruntime-gpu==1.20.2
nvidia-cudnn-cu12==9.1.0.70
```

如果日志出现 `libcudnn_adv.so.9: cannot open shared object file`，说明缺 cuDNN 9；先确认正在使用包含 `MOSS_CUDNN_PACKAGE=nvidia-cudnn-cu12==9.1.0.70` 的 GPU 镜像，或暂时使用 `moss-nano-cpu`。

## 5. MOSS 参考音频克隆：音频到底放哪？

最容易误解的一点：**MOSS 参考音频不要放进 `models/voices`。**

`models/voices` 是 Kokoro 的 `.pt` 音色目录。MOSS 克隆有三种方式：

| 方式 | 参考音频位置 | 适合 |
|---|---|---|
| HTTP multipart 上传 | 客户端本机任意路径，例如 `./reference.wav`，请求时 `-F prompt_audio=@reference.wav` 上传 | 最推荐，一次请求带一次参考音频 |
| WebSocket base64 | 客户端读取本地文件，转成 base64/data URL，放进首个 JSON 的 `prompt_audio.data` | 流式克隆、网页上传 |
| 服务端默认参考音频 | 挂载到容器内，例如 `/app/prompts/reference.wav`，设置 `MOSS_PROMPT_AUDIO_PATH` | 固定一个默认克隆音色 |

推荐参考音频：3-10 秒、单人、清晰、少噪音。过长音频会被 `MOSS_PROMPT_AUDIO_MAX_SECONDS` 裁剪，也会增加显存和延迟压力。

### 5.1 HTTP 克隆上传

```bash
curl -X POST http://localhost:8000/api/tts \
  -F model=moss-nano-cpu \
  -F text="这是克隆测试。" \
  -F voice=Junhao \
  -F response_format=wav \
  -F prompt_audio=@reference.wav \
  --output clone.wav
```

如果设置了 `KOKORO_API_KEY`，加：

```bash
-H "Authorization: Bearer YOUR_TOKEN"
```

如果返回 400 `当前模型不支持参考音频克隆`，说明请求打到了 Kokoro 或其他非克隆模型。请指定：

```bash
-F model=moss-nano-cpu
```

或先切换模型：

```bash
curl -X POST http://localhost:8000/v1/models/switch \
  -H "Content-Type: application/json" \
  -d '{"model":"moss-nano-cpu","unload_previous":true}'
```

### 5.2 WebSocket 流式克隆

WebSocket 不能 multipart 上传。参考音频需要放在首个 JSON 的 `prompt_audio.data` 字段中：

```json
{
  "model": "moss-nano-cpu",
  "text": "这是克隆流式测试。",
  "voice": "Junhao",
  "format": "pcm_s16le",
  "prompt_audio": {
    "filename": "reference.wav",
    "data": "<base64-or-data-url>"
  }
}
```

浏览器端用 `FileReader.readAsDataURL(file)` 即可得到 `data`。Python 端用：

```python
import base64
prompt_b64 = base64.b64encode(open("reference.wav", "rb").read()).decode("ascii")
```

完整浏览器和 Python 示例见 `/api-docs` 或 [API 参考](API_REFERENCE.md)。

### 5.3 服务端默认参考音频

如果每次都想用同一个参考音频，可以挂载到容器内：

```yaml
volumes:
  - ../../prompts:/app/prompts:ro

environment:
  - MOSS_PROMPT_AUDIO_PATH=/app/prompts/reference.wav
  - MOSS_PROMPT_AUDIO_MAX_SECONDS=10
  - MOSS_PROMPT_CACHE_MAX_ITEMS=8
```

然后请求不再需要上传 `prompt_audio`：

```bash
curl -X POST http://localhost:8000/api/tts \
  -F model=moss-nano-cpu \
  -F text="这次请求会使用服务端默认参考音频。" \
  -F voice=Junhao \
  -F response_format=wav \
  --output clone-default.wav
```

## 6. MOSS 速度不稳定、爆音或 clone OOM

MOSS-TTS-Nano 参数量不大，但 clone 路径会先用 codec encoder 编码参考音频。参考音频过长时，即使是 8GB 显存也可能出现多 GB 临时 buffer 分配，表现为 CUDA OOM、爆音、失真或速度忽快忽慢。

建议先保持这些配置：

```bash
KOKORO_MAX_CONCURRENT_REQUESTS=1
MOSS_PROMPT_AUDIO_MAX_SECONDS=8
MOSS_PROMPT_CACHE_MAX_ITEMS=6
MOSS_SAMPLE_MODE=fixed
MOSS_SEED=1234
MOSS_STREAM_CHUNK_SECONDS=0.35
MOSS_OUTPUT_PEAK_NORMALIZE_ENABLED=true
MOSS_OUTPUT_TARGET_PEAK=0.90
MOSS_OUTPUT_GAIN=1.0
```

排查：

```bash
docker logs -f angevoice-gpu | grep -Ei "moss|cuda|oom|clip|quality|fallback"
curl http://127.0.0.1:8101/v1/models/current
```

如果 `last_output_quality.max_abs_before` 经常接近或超过 `1.0`，不要提高 `MOSS_OUTPUT_GAIN`。如果 clone 一直 OOM，继续缩短 `MOSS_PROMPT_AUDIO_MAX_SECONDS` 到 `5`，或先切换 `moss-nano-cpu` 验证文本和参考音频本身。

如果日志显示 `requested=cuda actual=cpu`，或出现 `CUBLAS_STATUS_ALLOC_FAILED` / `BFCArena::AllocateRawInternal`，说明 CUDA provider 初始化失败。优先检查显存是否被其他容器占用：

```bash
nvidia-smi
docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}"
```

单张 8GB 卡不建议同时跑多个会加载 GPU 模型的容器。`MOSS_CUDA_MEMORY_LIMIT_MB` 默认保持 `0`；只有在 Tesla P4、RTX 3070 这类紧张环境排障时，才建议手动设置成 `4096` 或更低测试。

## 7. 输出音频没有持久化

确认 Docker Compose 挂载和环境变量：

```yaml
- ../../outputs:/app/outputs
```

```bash
ANGEVOICE_SAVE_OUTPUTS=true
ANGEVOICE_OUTPUT_DIR=/app/outputs
ANGEVOICE_OUTPUT_MAX_FILES=1000
```

只有 HTTP `/api/tts`、`/v1/audio/speech` 和批量接口会保存结果；WebSocket 实时播放默认不落盘。

## 8. MP3 返回 400 或 500

MP3 默认关闭。开启：

```bash
KOKORO_MP3_ENABLED=true
KOKORO_MP3_BITRATE=192k
```

检查 ffmpeg：

```bash
ffmpeg -version
```

## 9. 服务启动时报 API Key 或管理接口错误

v2.6 会在启动时拦截不安全配置。以下配置会失败：

```bash
KOKORO_API_KEY=change-me
KOKORO_ADMIN_ENABLED=true
KOKORO_API_KEY=
KOKORO_VOICE_UPLOAD_ENABLED=true
KOKORO_ADMIN_ENABLED=false
```

修复：

```bash
KOKORO_API_KEY=<paste-generated-token-here>
KOKORO_ADMIN_ENABLED=false
KOKORO_VOICE_UPLOAD_ENABLED=false
```

需要管理接口时再开启 `KOKORO_ADMIN_ENABLED=true`，并保留强 API Key。

## 10. `/stats` 或 `/requests` 返回 401

如果设置了：

```bash
KOKORO_API_KEY=<paste-generated-token-here>
```

请求需要携带：

```bash
curl http://127.0.0.1:8000/stats \
  -H "Authorization: Bearer YOUR_GENERATED_TOKEN"
```

Studio Web UI 可在右上角设置面板保存 Bearer Token。

## 11. WebSocket 连接成功但无音频

检查首个消息是否包含必要字段：

```json
{
  "text": "你好世界",
  "voice": "zm_010",
  "speed": 1.0,
  "format": "pcm_s16le",
  "binary": false
}
```

如果设置了 API Key，需要在首个 JSON 中传 `token`，或通过 WebSocket header 传 `Authorization`。

如果通过 Nginx、Caddy 或开发代理访问，确认代理支持 WebSocket upgrade，并转发：

```http
Connection: upgrade
Upgrade: websocket
```

本地直接连接 `ws://host:port/ws/v1/tts` 正常，但通过代理失败时，优先检查这一项。

## 12. 音色列表为空

检查目录：

```bash
ls models/voices/*.pt
```

容器中检查：

```bash
docker exec -it angevoice-gpu ls -lh /app/models/voices
```

如果目录为空，重新下载模型音色。

## 13. 上传 Kokoro `.pt` 音色失败

上传接口需要同时开启：

```bash
KOKORO_ADMIN_ENABLED=true
KOKORO_VOICE_UPLOAD_ENABLED=true
KOKORO_API_KEY=<paste-generated-token-here>
```

Docker 还需要 voices 目录可写：

```yaml
- ../../models/voices:/app/models/voices:rw
```

注意：这和 MOSS 参考音频克隆不是同一个功能。MOSS 参考音频走 `/api/tts` 的 `prompt_audio`，或 WebSocket 首包的 `prompt_audio.data`。

## 14. Windows / 本机访问 Docker 服务失败

确认端口映射，例如 GPU profile 默认：

```yaml
ports:
  - "8101:8000"
```

访问宿主机端口：

```text
http://localhost:8101
```

不是容器内部端口 `8000`。

## 15. 重构后旧脚本还能不能用？

可以。v2.6 保留：

```bash
kokoro-tts serve
kokoro-tts synth "你好"
```

同时推荐新命令：

```bash
angevoice serve
angevoice synth "你好"
```

Python import 包名仍是：

```python
from kokoro_tts import TTSEngine
```

## 16. 请求返回 429 Too Many Requests

出现 429 说明触发了内置限流或并发队列上限。

**两种情况：**

| 响应体 `error` 字段 | 原因 | 处理 |
|---|---|---|
| `rate_limit_exceeded` | 单客户端 QPS 超限 | 降低请求频率，客户端读取 `Retry-After` 头退避重试 |
| `queue_full` | 全局并发请求已达上限 | 等待正在处理的请求完成后再发新请求 |

**查看当前限流配置：**

```bash
curl -s http://localhost:8101/health | python3 -m json.tool
```

**调整限流参数：**

```bash
# 放宽 QPS（仅公网部署时谨慎调整）
KOKORO_RATE_LIMIT_QPS=20
KOKORO_RATE_LIMIT_BURST=40

# 放宽全局并发
KOKORO_MAX_QUEUE_LENGTH=50
```

设为 0 可完全禁用对应限制（仅建议本地/可信环境）。

**客户端最佳实践：**

```python
import time, requests

def tts_with_retry(url, payload, max_retries=3):
    for attempt in range(max_retries):
        resp = requests.post(url, json=payload)
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", 1))
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp.content
    raise RuntimeError("Rate limited after retries")
```

详见 [安全说明](SECURITY.md) 中的速率限制配置。
