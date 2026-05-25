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
ls -lh models/models--hexgrad--Kokoro-82M-v1.1-zh/voices/
head -5 models/models--hexgrad--Kokoro-82M-v1.1-zh/kokoro-v1_1-zh.pth
```

如果看到 `version https://git-lfs.github.com/spec/v1`，说明它只是 LFS 指针，不是真实权重。

修复：

```bash
pip install huggingface_hub
mkdir -p models/models--hexgrad--Kokoro-82M-v1.1-zh
huggingface-cli download hexgrad/Kokoro-82M-v1.1-zh \
  --local-dir models/models--hexgrad--Kokoro-82M-v1.1-zh \
  --include "config.json" "kokoro-v1_1-zh.pth" "voices/*.pt"
```


## Git LFS pointer 文件专项

GitHub 的 Source code ZIP 和未安装 `git-lfs` 的普通 `git clone` 可能只拿到指针文件，而不是真实模型。打开模型文件如果看到：

```text
version https://git-lfs.github.com/spec/v1
oid sha256:...
size ...
```

说明它不是可用权重。AngeVoice 会用文件大小和内容特征避免把 pointer 当真实模型；首次运行会按 `ANGEVOICE_MODEL_SOURCE` 自动下载真实模型。国内网络建议保持 `ANGEVOICE_MODEL_SOURCE=auto`，让服务先探测 Hugging Face / ModelScope 可达性，再决定源站。

修复方式：

```bash
git lfs install
git lfs pull
# 或删除 pointer 文件后重启服务，让 AngeVoice 自动下载
```


### Kokoro 报 `Weights only load failed` / `Unsupported operand 118`

这个错误几乎总是因为本地 `kokoro-v1_1-zh.pth` 或 `models/models--hexgrad--Kokoro-82M-v1.1-zh/voices/*.pt` 不是二进制权重，而是 Git LFS 指针文本。例如：

```text
version https://git-lfs.github.com/spec/v1
oid sha256:...
size ...
```

2.6.5.3 之后，AngeVoice 会更精准地检查 Kokoro 主模型和音色文件：

- 主模型会检查体积和文件头，避免把不完整权重当成真实模型；
- 音色文件本身可以比较小，因此优先检查 PyTorch zip/pickle 文件头；
- 内容以 Git LFS 指针、HTML/JSON 错误页开头会被跳过；
- 无效本地音色不会作为本地路径传给 Kokoro，且同一路径只 warning 一次，避免长文本合成刷屏。

如果仍然报错，通常是 Hugging Face / ModelScope 缓存里也残留了错误文件。可删除缓存后重启：

```bash
# 统一模型目录为 ./models；清理 Kokoro HF/ModelScope 缓存后重启即可重新下载
rm -rf models/models--hexgrad--Kokoro-82M-v1.1-zh/blobs
rm -rf models/models--hexgrad--Kokoro-82M-v1.1-zh/snapshots
rm -rf models/modelscope-cache/hub/AI-ModelScope_Kokoro-82M-v1.1-zh

# 或只删除源码包里的小型 LFS 指针，让服务重新下载/回退上游缓存
find models/models--hexgrad--Kokoro-82M-v1.1-zh -type f -size -10k \
  \( -name "*.pt" -o -name "*.pth" \) -delete
```

不要为了解决该错误盲目把 `torch.load(weights_only=False)` 打开。只有完全可信的权重才能关闭 `weights_only`，否则存在任意代码执行风险。

## 2. Docker 能启动但 `/health` 很久才 ok

首次加载模型会下载或初始化权重，GPU 机器也需要 CUDA 初始化。建议：

```bash
docker logs -f angevoice-gpu
curl http://127.0.0.1:8101/health
```

确保 Compose 中统一模型目录已挂载：

```yaml
- ../../models:/app/models
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

如果 `MOSS-TTS-Nano` 显示不可用，通常是官方 OpenMOSS runtime 没有安装、`MOSS_TTS_NANO_PATH` 指向错误，或当前镜像不是 v2.6 之后的 MOSS 预装画像。

检查：

```bash
docker compose config | grep -E "ANGEVOICE_ENABLED_MODELS|MOSS_CUDA_ENABLED|MOSS_EXECUTION_PROVIDER"
docker exec -it angevoice-gpu python3 - <<'PY'
import importlib.util
print(importlib.util.find_spec("onnx_tts_runtime"))
PY
```

CPU 镜像默认令 `moss` 使用 CPU provider；legacy-gpu 虽然预装 CUDA 11.8 兼容依赖，但默认同样令 MOSS 使用 CPU provider。请先尝试通用 `gpu` 画像，只有它无法启动或不稳定时再使用 `legacy-gpu`。

如果 CUDA 模式失败但 CPU 可用，保持：

```bash
MOSS_AUTO_FALLBACK_CPU=true
MOSS_QUALITY_GATE_ENABLED=true
```

老架构 GPU 要试 CUDA MOSS 时，需要同时设置：

```bash
ANGEVOICE_ENABLED_MODELS=kokoro,moss,zipvoice
MOSS_CUDA_ENABLED=true
MOSS_EXECUTION_PROVIDER=cuda
```

Tesla P4 / P40 / V100 等老卡如果宿主机驱动较新，也建议优先尝试通用 `gpu` 画像。MOSS CUDA 推荐组合：

```text
onnxruntime-gpu==1.20.2
nvidia-cudnn-cu12==9.1.0.70
```

如果日志出现 `libcudnn_adv.so.9: cannot open shared object file`，说明缺 cuDNN 9；先确认正在使用包含 `MOSS_CUDNN_PACKAGE=nvidia-cudnn-cu12==9.1.0.70` 的 GPU 镜像，或暂时令 `moss` 使用 CPU provider。

## 5. MOSS 参考音频克隆：音频到底放哪？

最容易误解的一点：**MOSS 参考音频不要放进 `models/models--hexgrad--Kokoro-82M-v1.1-zh/voices`。**

`models/models--hexgrad--Kokoro-82M-v1.1-zh/voices` 是 Kokoro 的 `.pt` 音色目录。MOSS 克隆有三种方式：

| 方式 | 参考音频位置 | 适合 |
|---|---|---|
| HTTP multipart 上传 | 客户端本机任意路径，例如 `./reference.wav`，请求时 `-F prompt_audio=@reference.wav` 上传 | 最推荐，一次请求带一次参考音频 |
| WebSocket base64 | 客户端读取本地文件，转成 base64/data URL，放进首个 JSON 的 `prompt_audio.data` | 流式克隆、网页上传 |
| 服务端默认参考音频 | 挂载到容器内，例如 `/app/prompts/reference.wav`，设置 `MOSS_PROMPT_AUDIO_PATH` | 固定一个默认克隆音色 |

推荐参考音频：3-10 秒、单人、清晰、少噪音。过长音频会被 `MOSS_PROMPT_AUDIO_MAX_SECONDS` 裁剪，也会增加显存和延迟压力。

### 5.1 HTTP 克隆上传

```bash
curl -X POST http://localhost:8000/api/tts \
  -F model=moss \
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
-F model=moss
```

或先切换模型：

```bash
curl -X POST http://localhost:8000/v1/models/switch \
  -H "Content-Type: application/json" \
  -d '{"model":"moss","unload_previous":true}'
```

### 5.2 WebSocket 流式克隆

WebSocket 不能 multipart 上传。参考音频需要放在首个 JSON 的 `prompt_audio.data` 字段中：

```json
{
  "model": "moss",
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
  - MOSS_PROMPT_AUDIO_MAX_SECONDS=8
  - MOSS_PROMPT_CACHE_MAX_ITEMS=8
```

然后请求不再需要上传 `prompt_audio`：

```bash
curl -X POST http://localhost:8000/api/tts \
  -F model=moss \
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
MOSS_STREAM_CHUNK_SECONDS=0.40
MOSS_STREAM_CHUNK_MIN_FLOOR=0.10
MOSS_OUTPUT_PEAK_NORMALIZE_ENABLED=true
MOSS_REALTIME_STREAMING_DECODE=true
MOSS_OUTPUT_TARGET_PEAK=0.86
MOSS_OUTPUT_GAIN=0.94
MOSS_OUTPUT_DECLICK_ENABLED=true
MOSS_OUTPUT_EDGE_FADE_MS=1.5
```

排查：

```bash
docker logs -f angevoice-gpu | grep -Ei "moss|cuda|oom|clip|quality|fallback"
curl http://127.0.0.1:8101/v1/models/current
```

如果 `last_output_quality.max_abs_before` 经常接近或超过 `1.0`，不要提高 `MOSS_OUTPUT_GAIN`。如果 clone 一直 OOM，继续缩短 `MOSS_PROMPT_AUDIO_MAX_SECONDS` 到 `5`，或先令 `moss` 使用 CPU provider 验证文本和参考音频本身。

### Web 或小智播放 MOSS 有电流音、卡顿、爆音

优先使用质量优先配置：

```bash
MOSS_REALTIME_STREAMING_DECODE=true
MOSS_OUTPUT_TARGET_PEAK=0.86
MOSS_OUTPUT_GAIN=0.94
MOSS_OUTPUT_DECLICK_ENABLED=true
MOSS_OUTPUT_EDGE_FADE_MS=1.5
```

`MOSS_REALTIME_STREAMING_DECODE=true` 会更早推送小音频块，但在部分参考音频、CUDA/ONNX 组合和小喇叭播放链路上容易放大 chunk 边界不连续，表现为“刺”“噗”“电流音”。默认开启逐帧实时解码以降低首包等待、改善 Web/小智体感；若个别设备出现噪声、卡顿或边界不连续，可改为 false 走质量优先整块生成。


如果日志显示 `requested=cuda actual=cpu`，或出现 `CUBLAS_STATUS_ALLOC_FAILED` / `BFCArena::AllocateRawInternal`，说明 CUDA provider 初始化失败。优先检查显存是否被其他容器占用：

```bash
nvidia-smi
docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}"
```

单张 8GB 卡不建议同时跑多个会加载 GPU 模型的容器。`MOSS_CUDA_MEMORY_LIMIT_MB` 默认保持 `0`；只有在 Tesla P4、RTX 3070 这类紧张环境排障时，才建议手动设置成 `4096` 或更低测试。

正式 Docker 与 fnOS 模板默认对三模型开启进程级隔离；它和播放音质不是同一个开关，而是空闲 RAM/VRAM 回收与卡死恢复策略：

```env
KOKORO_PROCESS_ISOLATION_ENABLED=true
MOSS_PROCESS_ISOLATION_ENABLED=true
MOSS_PROCESS_ISOLATION_PROVIDERS=cpu,cuda
ZIPVOICE_PROCESS_ISOLATION_ENABLED=true
ANGEVOICE_ENGINE_PROCESS_KILL_GRACE_SECONDS=2
ANGEVOICE_STARTUP_PRELOAD_ENABLED=false
```

开启隔离后，模型由可销毁 Worker 承载；空闲释放、模型切换、流式取消或超时终止 Worker 后，下次请求会自动重新唤醒。管理后台允许关闭 Kokoro / ZipVoice 隔离用于兼容性调试，但页面会提示线程内运行不保证主机 RAM 完整回收。若希望开机即热启动，可开启启动预载；预载同样通过 Worker 完成，不将模型载入 API 主进程。

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
KOKORO_API_KEY=<your-api-key>
KOKORO_ADMIN_ENABLED=true
ANGEVOICE_ADMIN_PASSWORD=
KOKORO_VOICE_UPLOAD_ENABLED=true
KOKORO_ADMIN_ENABLED=false
```

修复：

```bash
KOKORO_API_KEY=auto
ANGEVOICE_API_KEY_FILE=/app/credentials/.angevoice-api-key
KOKORO_ADMIN_ENABLED=false
KOKORO_VOICE_UPLOAD_ENABLED=false
```

需要管理后台/接口时再开启：

```bash
KOKORO_ADMIN_ENABLED=true
ANGEVOICE_ADMIN_PASSWORD=<strong-password>
```

公网部署建议同时保留强 API Key。

## 10. `/stats` 或 `/requests` 返回 401

如果设置了手动 key，或生产模板使用 `KOKORO_API_KEY=auto` 自动生成了 key：

```bash
KOKORO_API_KEY=auto
ANGEVOICE_API_KEY_FILE=/app/credentials/.angevoice-api-key
# 或 KOKORO_API_KEY=<your-real-secret>
```

请求需要携带：

```bash
curl http://127.0.0.1:8000/stats \
  -H "Authorization: Bearer YOUR_GENERATED_TOKEN"
```

Studio Web UI 会在需要鉴权但本地没有 token 时自动打开设置面板；已开启管理后台时可跳到 `/admin` 的 API Key 区域查看/轮换，未开启时请查看启动日志或 `ANGEVOICE_API_KEY_FILE`。

### 查看自动生成 API Key

一键 Docker 安装的默认路径：

```bash
cat /opt/angevoice/credentials/.angevoice-api-key
```

如果你用自定义目录安装，把 `/opt/angevoice` 换成自己的项目目录。不要把完整 key 发到论坛、Issue 或群聊截图里。

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
ls models/models--hexgrad--Kokoro-82M-v1.1-zh/voices/*.pt
```

容器中检查：

```bash
docker exec -it angevoice-gpu ls -lh /app/models/models--hexgrad--Kokoro-82M-v1.1-zh/voices
```

如果目录为空，重新下载模型音色。

从 2.6.5.3.2 起，前端音色库也会扫描 Hugging Face 缓存快照目录：

```text
/app/models/models--hexgrad--Kokoro-82M-v1.1-zh/snapshots/<sha>/voices/
```

因此即使上游 `kokoro` 包把音色下载到缓存快照里，Studio 也应能显示音色。若仍显示 0，请检查 `.pt` 是否是 100 多字节的 Git LFS 指针，或是否是 HTML/JSON 下载错误页。

## 13. 上传 Kokoro `.pt` 音色失败

上传接口需要同时开启：

```bash
KOKORO_ADMIN_ENABLED=true
ANGEVOICE_ADMIN_PASSWORD=<strong-password>
KOKORO_VOICE_UPLOAD_ENABLED=true
KOKORO_API_KEY=auto
# 或 KOKORO_API_KEY=<your-real-secret>
```

Docker 还需要 voices 目录可写：

```yaml
- ../../models/models--hexgrad--Kokoro-82M-v1.1-zh/voices:/app/models/models--hexgrad--Kokoro-82M-v1.1-zh/voices:rw
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

## WebSocket 一直卡在“建立流式连接”

如果长文本或 MOSS CUDA 合成中途刷新页面、点击停止后再次生成一直卡住，优先确认已经使用 2.6.5.3 或更新版本。当前版本做了三件事：

1. WebSocket 发送失败会立即标记请求取消，不再把断开的连接当作服务端错误反复发送。
2. MOSS 隔离 worker 的流式超时按“无任何事件的空闲时间”计算，而不是整段长文本的总时长。
3. 用户取消后会杀掉隔离 worker，并把模型状态标记为需要下次重载，避免旧 worker 残留导致后续请求卡住。

临时恢复方式：

```bash
AngeVoice
# 选择“重启当前画像”
```

或直接：

```bash
bash scripts/install.sh --restart
```

### 管理后台能弹出登录框但无法进入

检查环境变量：

```bash
grep -E 'KOKORO_ADMIN_ENABLED|ANGEVOICE_ADMIN_USERNAME|ANGEVOICE_ADMIN_PASSWORD' docker/angevoice.env
```

必须满足：

```bash
KOKORO_ADMIN_ENABLED=true
ANGEVOICE_ADMIN_PASSWORD=你的强密码
```

然后重启容器：

```bash
AngeVoice --restart
# 或 docker compose restart
```

如果账号或密码包含中文，建议使用最新版本。管理后台 Basic Auth 已经改为按原始字节解析，并同时兼容 UTF-8 / latin-1，避免浏览器编码差异导致一直无法登录。

公网部署时不建议直接暴露 `/admin`。建议只在内网访问，或通过反向代理限制 IP。


## 反代后限流 IP 不准 / 裸露公网被绕过

默认 `KOKORO_TRUST_PROXY_HEADERS=false`，限流使用 TCP 对端 IP，不读取客户端可伪造的 `X-Forwarded-For`。只有确认服务位于可信反向代理后面，且外部不能直连后端端口时，才设置：

```bash
KOKORO_TRUST_PROXY_HEADERS=true
```


## MOSS 长文本仍有卡顿/爆音

优先确认 `MOSS_SEGMENT_LENGTH=120` 和 `MOSS_MIXED_ENGLISH_POLICY=translate` 已生效。它只影响 MOSS 分段，不影响 Kokoro。P4/NAS 默认用较短分段降低中英文混合尾部变调、卡顿和失真；高显存机器可在后台尝试 180~260。


## MOSS 切换时报 browser_onnx model assets not found

如果切换 `moss` 时看到 `browser_onnx model assets not found under the provided --model-dir`，说明 `MOSS_MODEL_DIR` 存在但没有真正的 ONNX 模型资产。2.6.5.3.2 起，服务会在目录为空、只有 README、Git LFS 指针或占位文件时自动尝试从 `MOSS_MODELSCOPE_REPO` 下载。官方 ModelScope 包中的大权重文件是 `*.data`，不是所有 ONNX 图文件都会超过 1MB；2.6.5.3.2 已按 `browser_poc_manifest.json` + 真实 `*.data`/ONNX 资产判断。仍失败时请检查网络，或手动把 `browser_poc_manifest.json`、`moss_tts_global_shared.data`、`moss_tts_local_shared.data` 及 ONNX 文件放入 `/app/models/MOSS-TTS-Nano-100M-ONNX`。
