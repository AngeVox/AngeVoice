# Legacy GPU / 老显卡兼容镜像

> Conservative CUDA 11.8 deployment profile for older NVIDIA GPUs, older driver stacks, NAS boxes, and low-power home servers.
>
> 面向旧 NVIDIA 显卡、旧驱动、NAS 和低功耗家用服务器的保守 CUDA 11.8 部署方案。

## When to use / 适用场景

Use this profile when the default GPU image does not work well in your environment, for example:

适合在以下情况下使用：

- CUDA 12 image fails to start or behaves unstably.
- Your host uses an older but still supported NVIDIA driver.
- You run the service on a NAS, home server, or low-power machine.
- You prefer conservative runtime settings over maximum throughput.
- You observe audio artifacts or instability with aggressive acceleration stacks.

- 默认 CUDA 12 镜像无法启动或运行不稳定。
- 宿主机使用较旧但仍可用的 NVIDIA 驱动。
- 服务运行在 NAS、家用服务器或低功耗主机上。
- 更看重稳定性，而不是极限吞吐。
- 使用激进加速栈时出现音频噪声、爆音或推理异常。

## Quick start / 快速启动

```bash
cd docker/legacy-gpu
docker compose up -d --build
```

Default port / 默认端口：

```bash
http://localhost:8102
```

Health check / 健康检查：

```bash
curl http://localhost:8102/health
curl http://localhost:8102/stats
curl http://localhost:8102/requests
```

Speech test / 合成测试：

```bash
curl -X POST http://localhost:8102/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"model":"kokoro","input":"你好世界，这是老显卡兼容镜像测试。","voice":"zm_010","response_format":"wav"}' \
  --output legacy-test.wav
```

## Recommended defaults / 推荐默认值

```bash
KOKORO_WORKERS=1
KOKORO_MAX_CONCURRENT_REQUESTS=1
KOKORO_REQUEST_TIMEOUT_SECONDS=600
KOKORO_SEGMENT_LENGTH=80
KOKORO_CACHE_ENABLED=true
KOKORO_CACHE_MAX_ITEMS=64
KOKORO_STREAM_BINARY_ENABLED=false
```

Why / 原因：

- `workers=1`: avoids multiple processes loading the model into GPU memory.
- `max_concurrent_requests=1`: keeps GPU memory and inference scheduling stable.
- `request_timeout_seconds=600`: gives slower systems more time for long text.
- `segment_length=80`: lowers single-segment failure risk.
- `stream_binary_enabled=false`: JSON/base64 mode is easier to debug first.

- `workers=1`：避免多个进程重复加载模型到显存。
- `max_concurrent_requests=1`：让显存和推理调度更稳定。
- `request_timeout_seconds=600`：给慢机器和长文本更多执行时间。
- `segment_length=80`：降低单段过长导致失败的概率。
- `stream_binary_enabled=false`：先用 JSON/base64 更容易排查问题。

## Development hot reload / 开发热更新

For development or local testing, uncomment this line in `docker-compose.yml`:

开发或本地测试时，可以取消注释：

```yaml
- ../../src:/app/src:ro
```

Then updates usually only require:

之后通常只需要：

```bash
git pull
docker compose restart
```

For production, keep the source mount disabled and rebuild the image:

生产环境建议不要挂载源码，使用固定镜像：

```bash
docker compose up -d --build
```

## Optional MP3 / 可选 MP3

This image includes `ffmpeg`, but MP3 output is disabled by default.

镜像已内置 `ffmpeg`，但 MP3 输出默认关闭。

Enable it in `docker-compose.yml`:

在 `docker-compose.yml` 中开启：

```yaml
- KOKORO_MP3_ENABLED=true
- KOKORO_MP3_BITRATE=192k
```

Request example / 请求示例：

```bash
curl -X POST http://localhost:8102/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"model":"kokoro","input":"这是 MP3 测试。","voice":"zm_010","response_format":"mp3"}' \
  --output test.mp3
```

## Optional MOSS / 可选 MOSS

Legacy GPU preinstalls the MOSS runtime, including a CUDA 11.8 compatible
`onnxruntime-gpu` package from the official ONNX Runtime CUDA 11 feed, but its
Compose profile exposes only Kokoro and MOSS CPU by default. This keeps NAS and
older driver stacks stable while still allowing advanced users to try MOSS CUDA
without rebuilding the image.

ONNX Runtime CUDA install reference:
https://onnxruntime.ai/docs/install/

老显卡镜像会预装 MOSS runtime，包括 CUDA 11.8 兼容的 `onnxruntime-gpu`
依赖，但 Compose 默认只开放 Kokoro 和 MOSS CPU。这样能保证 NAS 与旧驱动长期稳定，同时让高级用户无需重建镜像就能尝试 MOSS CUDA。

```yaml
INSTALL_MOSS: "true"
ANGEVOICE_ENABLED_MODELS=kokoro,moss-nano-cpu
MOSS_EXECUTION_PROVIDER=cpu
MOSS_CUDA_ENABLED=false
MOSS_MODEL_DIR=/opt/MOSS-TTS-Nano/models
MOSS_PROMPT_UPLOAD_MAX_BYTES=20971520
```

Generated HTTP audio and MOSS ONNX assets are persisted by the Compose mounts:

HTTP 合成结果和 MOSS ONNX 模型会通过 Compose 挂载持久化：

```yaml
- ../../moss_models:/opt/MOSS-TTS-Nano/models
- ../../outputs:/app/outputs
```

To try MOSS CUDA on legacy GPU, manually add `moss-nano-cuda` and set
`MOSS_CUDA_ENABLED=true`; keep it only if the built-in self-test and listening
test are clean.

如果要在 legacy GPU 上尝试 MOSS CUDA，需要手动加入 `moss-nano-cuda` 并设置
`MOSS_CUDA_ENABLED=true`；只有内置自检和人工试听都正常时才建议长期使用。

For Tesla P4 specifically, the modern GPU profile has been validated with
`onnxruntime-gpu==1.20.2` and `nvidia-cudnn-cu12==9.1.0.70`. Use the legacy
profile when CUDA 12/cuDNN 9 is not suitable for the host, and keep MOSS on CPU
unless the CUDA 11.8 path passes validation.

针对 Tesla P4，现代 GPU 画像已用 `onnxruntime-gpu==1.20.2` 和
`nvidia-cudnn-cu12==9.1.0.70` 验证 MOSS CUDA 可运行。如果宿主机不适合 CUDA 12/cuDNN 9，则使用 legacy 画像，并让 MOSS 保持 CPU；除非 CUDA 11.8 路径已经通过验证。

## Admin and voice upload / 管理接口与音色上传

Admin APIs are disabled by default. Enable them only with an API key:

管理接口默认关闭。建议只在设置 API Key 后开启：

```yaml
- KOKORO_ADMIN_ENABLED=true
- KOKORO_API_KEY=<paste-generated-token-here>
```

Voice upload also requires:

上传音色还需要：

```yaml
- KOKORO_VOICE_UPLOAD_ENABLED=true
- ../../models/voices:/app/models/voices:rw
```

## Troubleshooting / 排障建议

If the container cannot see the GPU:

如果容器无法识别 GPU：

```bash
nvidia-smi
docker run --rm --gpus all nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04 nvidia-smi
```

If synthesis works but audio has artifacts:

如果能合成但音频有噪声或失真：

- Keep `KOKORO_MAX_CONCURRENT_REQUESTS=1`.
- Reduce `KOKORO_SEGMENT_LENGTH` to `60` or `80`.
- Disable binary WebSocket mode during debugging.
- Avoid extra acceleration layers such as TensorRT or unsupported attention kernels.

- 保持 `KOKORO_MAX_CONCURRENT_REQUESTS=1`。
- 将 `KOKORO_SEGMENT_LENGTH` 降到 `60` 或 `80`。
- 调试阶段关闭 WebSocket binary 模式。
- 避免额外启用 TensorRT 或不兼容的 attention 加速。

## Related docs / 相关文档

- [Service profiles / 服务画像](../../docs/SERVICE_PROFILES.md)
- [v2.5 service features / v2.5 服务功能](../../docs/V2_5_FEATURES.md)
- [Roadmap / 长期路线图](../../docs/ROADMAP.md)
