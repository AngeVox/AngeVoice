# AngeVoice 安全说明 / Security Notes

AngeVoice 默认面向本地、内网或可信环境部署。若要公网暴露，请先确认鉴权、CORS、管理接口和上传接口都已按需收紧。

所有公开接口和鉴权位置见 [API 参考](API_REFERENCE.md)。

## 推荐安全基线

公网或半公网部署建议至少开启：

```bash
# 先生成真实密钥，例如：openssl rand -hex 32
KOKORO_API_KEY=<paste-generated-token-here>
KOKORO_ADMIN_ENABLED=false
KOKORO_VOICE_UPLOAD_ENABLED=false
KOKORO_CORS_ORIGINS=https://your-domain.example
```

AngeVoice 会在启动时拒绝明显不安全的组合：

- `KOKORO_API_KEY=change-me` 等占位值。
- `KOKORO_ADMIN_ENABLED=true` 但未设置 `ANGEVOICE_ADMIN_PASSWORD`。
- `KOKORO_VOICE_UPLOAD_ENABLED=true` 但未启用管理接口。

反向代理层建议：

- 只暴露必要路径，例如 `/v1/audio/speech`、`/ws/v1/tts`、`/health`。
- 限制 `/admin/*` 来源 IP，或完全不暴露。
- 启用 HTTPS。
- 设置请求体大小限制，避免超大文本或上传打满内存。
- 按 IP 或 API Key 做速率限制。

## API Key

设置 `KOKORO_API_KEY` 后，HTTP 接口需要：

```http
Authorization: Bearer YOUR_TOKEN
```

WebSocket 支持两种方式：

1. `Authorization: Bearer YOUR_TOKEN` header
2. 首个 JSON 消息中携带 `token`

```json
{"text":"你好", "voice":"zm_010", "token":"YOUR_TOKEN"}
```

内置 Studio Web UI 的设置面板会把 Bearer Token 存在浏览器本地，并同时用于 HTTP 请求和 WebSocket 首包。共享机器上使用后建议清除浏览器本地存储或点击设置面板中的移除。

## 管理接口

管理接口默认关闭：

```bash
KOKORO_ADMIN_ENABLED=false
```

开启后包含：

- `DELETE /admin/cache`
- `GET /admin/voices`
- `POST /admin/voices/upload`

建议只在本地或可信内网使用。公网部署时，必须设置 `ANGEVOICE_ADMIN_PASSWORD`，并建议同时设置强 API Key、在反向代理层限制来源。没有 `ANGEVOICE_ADMIN_PASSWORD` 时开启管理后台会直接启动失败。

## `.pt` 音色上传

`.pt` 上传默认关闭：

```bash
KOKORO_VOICE_UPLOAD_ENABLED=false
```

风险说明：

- `.pt` 是 PyTorch 权重文件格式，不应信任未知来源。
- 当前上传接口会限制扩展名和大小，但无法证明文件内容安全。
- 如果后续自动加载用户上传 `.pt`，应考虑隔离加载、签名校验或改用更安全的权重格式。

只建议上传自己生成或可信来源的音色文件。

## MOSS 参考音频上传

MOSS 参考音频克隆使用 `/api/tts` multipart 字段 `prompt_audio`，或 WebSocket 首包中的 `prompt_audio.data` base64，只在模型声明支持 `voice_clone` 时生效。上传文件会写入容器临时目录，合成结束后删除；MOSS 适配层会按 `MOSS_PROMPT_AUDIO_MAX_SECONDS` 裁剪后再编码，并缓存少量 prompt audio codes。合成结果是否保存由 `ANGEVOICE_SAVE_OUTPUTS` 控制。CPU 和老架构GPU 画像默认不暴露 MOSS CUDA，避免误切到未验证的 GPU 推理路径。

默认限制：

```bash
MOSS_PROMPT_UPLOAD_MAX_BYTES=20971520
MOSS_PROMPT_AUDIO_MAX_SECONDS=10
MOSS_PROMPT_CACHE_MAX_ITEMS=8
```

支持后缀：`wav/mp3/flac/ogg/m4a/aac`。公网部署时建议在反向代理层同步设置请求体大小限制，避免上传占满内存或磁盘。

## CORS

默认：

```bash
KOKORO_CORS_ORIGINS=http://localhost:8000
```

生产环境不要使用过宽的 CORS 来源。建议按域名明确配置：

```bash
KOKORO_CORS_ORIGINS=https://tts.example.com,https://app.example.com
```

如果确实配置 `KOKORO_CORS_ORIGINS=*`，服务会关闭 credential CORS 模式，避免浏览器拒绝通配来源和凭据组合。

## 速率限制与并发控制

公网部署建议启用内置限流，防止单客户端或异常脚本打满 GPU：

```bash
# 每客户端每秒最多 10 个请求，突发允许 20 个
KOKORO_RATE_LIMIT_QPS=10
KOKORO_RATE_LIMIT_BURST=20

# 全局最大并发请求（含排队），0=不限
KOKORO_MAX_QUEUE_LENGTH=20
```

- `KOKORO_RATE_LIMIT_QPS` — 基于令牌桶的 per-IP/per-API-key QPS 限制。设为 0 禁用。
- `KOKORO_RATE_LIMIT_BURST` — 令牌桶突发容量。
- `KOKORO_MAX_QUEUE_LENGTH` — 全局并发请求上限，超出立即返回 429。设为 0 禁用。

> ⚠️ 不要将限流设得过高。TTS 推理是 GPU 密集型操作，过高的并发会导致延迟飙升甚至 OOM。建议 `KOKORO_MAX_CONCURRENT_REQUESTS=1` + `KOKORO_MAX_QUEUE_LENGTH` 设为 CPU 核心数的 2-4 倍。

超出限流时，客户端会收到 `429 Too Many Requests` 响应和 `Retry-After` 头。客户端应据此退避重试。

## 资源消耗

TTS 推理是高成本操作。建议：

```bash
KOKORO_MAX_TEXT_LENGTH=10000
KOKORO_MAX_CONCURRENT_REQUESTS=1
KOKORO_REQUEST_TIMEOUT_SECONDS=300
KOKORO_BATCH_MAX_ITEMS=20
KOKORO_BATCH_CONCURRENCY=1
```

GPU 部署不要盲目提高 worker 和并发，否则容易显存翻倍、延迟增加或触发 OOM。

## 取消请求的语义

WebSocket `cancel` / `stop` 会阻止后续段落继续推送。Kokoro 与 MOSS CPU 线程内推理通常会在当前段结束后停止；MOSS CUDA 默认运行在隔离子进程中，超时或取消后的异常状态可通过终止 worker 进程恢复主服务。
