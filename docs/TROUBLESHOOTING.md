# AngeVoice 排障手册 / Troubleshooting

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
- ../../.cache/huggingface:/root/.cache/huggingface
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

如果 `moss-nano-cpu` / `moss-nano-cuda` 显示 `available=false`，通常是官方 OpenMOSS runtime 没有安装、`MOSS_TTS_NANO_PATH` 指向错误，或当前镜像不是 v2.5 之后的 MOSS 预装画像。先确认正在使用最新 Dockerfile/Compose，并检查：

```bash
docker compose config | grep -E "ANGEVOICE_ENABLED_MODELS|MOSS_CUDA_ENABLED|MOSS_EXECUTION_PROVIDER"
docker exec -it angevoice-gpu python3 - <<'PY'
import importlib.util
print(importlib.util.find_spec("onnx_tts_runtime"))
PY
```

CPU 镜像默认不注册 `moss-nano-cuda`；legacy GPU 画像虽然预装 MOSS GPU 依赖，但默认也会通过 `MOSS_CUDA_ENABLED=false` 隐藏 CUDA MOSS。

如果 CUDA 模式失败但 CPU 可用，保持：

```bash
MOSS_AUTO_FALLBACK_CPU=true
MOSS_QUALITY_GATE_ENABLED=true
```

旧显卡环境先用 `moss-nano-cpu`。`moss-nano-cuda` 需要 ONNX Runtime CUDA provider、CUDA/cuDNN 和驱动完全匹配；如果自检发现静音、NaN/Inf 或 clipping，AngeVoice 会拒绝该 CUDA 输出。legacy GPU 要试 CUDA MOSS 时，需要同时设置：

```bash
ANGEVOICE_ENABLED_MODELS=kokoro,moss-nano-cpu,moss-nano-cuda
MOSS_CUDA_ENABLED=true
MOSS_EXECUTION_PROVIDER=cuda
```

Tesla P4 实测结论：P4 可以跑 MOSS CUDA，但 GPU 镜像必须带 cuDNN 9。推荐组合：

```text
onnxruntime-gpu==1.20.2
nvidia-cudnn-cu12==9.1.0.70
```

如果通用 GPU 日志里出现 `libcudnn_adv.so.9: cannot open shared object file`，说明缺 cuDNN 9；此时不要强行长期运行 CUDA，先确认正在使用包含 `MOSS_CUDNN_PACKAGE=nvidia-cudnn-cu12==9.1.0.70` 的 GPU 镜像，或暂时使用 `moss-nano-cpu`。

## 5. MOSS 参考音频克隆不出现或上传失败

Studio 只会在当前模型支持 `voice_clone` 时显示“参考音频”。请先确认当前模型：

```bash
curl http://localhost:8000/v1/models/current
```

克隆上传只走 `/api/tts` multipart，WebSocket 暂不上传参考音频：

```bash
curl -X POST http://localhost:8000/api/tts \
  -F model=moss-nano-cpu \
  -F text="这是克隆测试。" \
  -F voice=Junhao \
  -F response_format=wav \
  -F prompt_audio=@reference.wav \
  --output clone.wav
```

如果返回 400 `当前模型不支持参考音频克隆`，说明请求打到了 Kokoro 或其他非克隆模型。支持后缀：`wav/mp3/flac/ogg/m4a/aac`，大小上限由 `MOSS_PROMPT_UPLOAD_MAX_BYTES` 控制。

## 6. 输出音频没有持久化

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

## 7. MP3 返回 400 或 500

MP3 默认关闭。开启：

```bash
KOKORO_MP3_ENABLED=true
KOKORO_MP3_BITRATE=192k
```

检查 ffmpeg：

```bash
ffmpeg -version
```

## 8. 服务启动时报 API Key 或管理接口错误

v2.5 会在启动时拦截不安全配置。以下配置会失败：

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

## 9. `/stats` 或 `/requests` 返回 401

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

## 10. WebSocket 连接成功但无音频

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

## 11. 音色列表为空

检查目录：

```bash
ls models/voices/*.pt
```

容器中检查：

```bash
docker exec -it angevoice-gpu ls -lh /app/models/voices
```

如果目录为空，重新下载模型音色。

## 12. 上传音色失败

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

## 13. Windows / 本机访问 Docker 服务失败

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

## 14. 重构后旧脚本还能不能用？

可以。v2.5 保留：

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
