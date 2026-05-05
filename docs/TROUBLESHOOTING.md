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

## 4. MP3 返回 400 或 500

MP3 默认关闭。开启：

```bash
KOKORO_MP3_ENABLED=true
KOKORO_MP3_BITRATE=192k
```

检查 ffmpeg：

```bash
ffmpeg -version
```

## 5. `/stats` 或 `/requests` 返回 401

如果设置了：

```bash
KOKORO_API_KEY=change-me
```

请求需要携带：

```bash
curl http://127.0.0.1:8000/stats \
  -H "Authorization: Bearer change-me"
```

## 6. WebSocket 连接成功但无音频

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

## 7. 音色列表为空

检查目录：

```bash
ls models/voices/*.pt
```

容器中检查：

```bash
docker exec -it angevoice-gpu ls -lh /app/models/voices
```

如果目录为空，重新下载模型音色。

## 8. 上传音色失败

上传接口需要同时开启：

```bash
KOKORO_ADMIN_ENABLED=true
KOKORO_VOICE_UPLOAD_ENABLED=true
KOKORO_API_KEY=change-me
```

Docker 还需要 voices 目录可写：

```yaml
- ../../models/voices:/app/models/voices:rw
```

## 9. Windows / 本机访问 Docker 服务失败

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

## 10. 重构后旧脚本还能不能用？

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
