# AngeVoice 安全说明 / Security Notes

AngeVoice 默认面向本地、内网或可信环境部署。若要公网暴露，请先确认鉴权、CORS、管理接口和上传接口都已按需收紧。

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
- `KOKORO_ADMIN_ENABLED=true` 但未设置 API Key。
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

建议只在本地或可信内网使用。公网部署时，必须设置强 API Key，并在反向代理层限制来源。没有 API Key 时开启管理接口会直接启动失败。

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

WebSocket `cancel` / `stop` 会阻止后续段落继续推送。如果某个段落已经进入同步模型推理，通常会在当前段结束后停止。它不是强制杀掉底层模型执行线程。
