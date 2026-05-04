# v2.4 服务功能说明

v2.4 在 v2.3 服务版基础上补充批量合成、管理接口、可选 MP3 转码和 WebSocket 主动取消能力。默认部署仍保持轻量稳定，管理类能力默认关闭，适合按需启用。

## 功能总览

| 功能 | 接口/配置 | 默认状态 |
|---|---|---|
| 批量合成 ZIP | `POST /v1/audio/batch` | 开启 |
| 支持格式查询 | `GET /v1/audio/formats` | 开启 |
| 清理缓存 | `DELETE /admin/cache` | 管理接口关闭 |
| 查看音色目录 | `GET /admin/voices` | 管理接口关闭 |
| 上传 `.pt` 音色 | `POST /admin/voices/upload` | 上传关闭 |
| MP3 输出 | `response_format=mp3` | 关闭 |
| WebSocket 取消 | `{"type":"cancel"}` / `{"type":"stop"}` | 开启 |

## 批量合成 ZIP

```http
POST /v1/audio/batch
```

请求示例：

```json
{
  "voice": "zm_010",
  "speed": 1.0,
  "response_format": "wav",
  "items": [
    {"text": "第一段", "filename": "001"},
    {"text": "第二段", "filename": "002", "voice": "zf_001"}
  ]
}
```

返回 `application/zip`，包含每条音频文件和 `manifest.json`。

限制项：

```bash
KOKORO_BATCH_ENABLED=true
KOKORO_BATCH_MAX_ITEMS=20
```

## 管理接口

管理接口默认关闭。开启时建议同时设置 API Key：

```bash
KOKORO_ADMIN_ENABLED=true
KOKORO_API_KEY=change-me
```

接口：

```http
DELETE /admin/cache
GET /admin/voices
POST /admin/voices/upload
```

上传音色还需要额外开启：

```bash
KOKORO_VOICE_UPLOAD_ENABLED=true
```

Docker 场景下需要将 voices 目录挂载为可写：

```yaml
- ../../models/voices:/app/models/voices:rw
```

安全建议：公网部署时不要裸开管理接口，至少设置 `KOKORO_API_KEY`，并通过反向代理限制来源。

## MP3 可选转码

MP3 默认关闭。开启前需要环境里存在 `ffmpeg`，官方 CPU/GPU Dockerfile 已包含该依赖。

```bash
KOKORO_MP3_ENABLED=true
KOKORO_MP3_BITRATE=192k
```

请求示例：

```json
{"response_format":"mp3"}
```

开启后返回 `audio/mpeg`。未开启时请求 `mp3` 会返回清晰的 400 错误，避免伪装格式。

## WebSocket 主动取消

流式合成过程中，客户端可以发送控制帧：

```json
{"type":"cancel"}
```

或：

```json
{"type":"stop"}
```

服务端会停止后续段落推送，并在 `/requests` 中记录 `cancelled` 状态。当前段落如果已经进入同步推理，会在当前段完成后停止后续段，这是逐段流式模式下更稳定的取消方式。

## Docker 调试模板

CPU/GPU 两套 `docker-compose.yml` 都提供注释模板，包含：

- 模型目录挂载
- `src` 源码热更新挂载
- voices 可写挂载
- workers / 并发 / 超时
- 缓存开关
- `/stats` 和 `/requests` 开关
- batch/admin/upload/mp3 配置
- CORS 配置说明

开发环境想要 `git pull + restart` 生效，可取消注释：

```yaml
- ../../src:/app/src:ro
```

生产环境建议使用镜像构建固定版本：

```bash
docker compose up -d --build
```

## 后续方向

- Web UI 音色管理和批量任务页面
- 可选多引擎插件化，例如 MOSS-TTS-Nano、CosyVoice、GPT-SoVITS
- 更完整的任务队列与后台作业持久化
