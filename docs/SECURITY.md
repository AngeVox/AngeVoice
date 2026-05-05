# AngeVoice 安全说明 / Security Notes

AngeVoice 默认面向本地、内网或可信环境部署。若要公网暴露，请先确认鉴权、CORS、管理接口和上传接口都已按需收紧。

## 推荐安全基线

公网或半公网部署建议至少开启：

```bash
KOKORO_API_KEY=replace-with-a-long-random-token
KOKORO_ADMIN_ENABLED=false
KOKORO_VOICE_UPLOAD_ENABLED=false
KOKORO_CORS_ORIGINS=https://your-domain.example
```

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

## 管理接口

管理接口默认关闭：

```bash
KOKORO_ADMIN_ENABLED=false
```

开启后包含：

- `DELETE /admin/cache`
- `GET /admin/voices`
- `POST /admin/voices/upload`

建议只在本地或可信内网使用。公网部署时，必须设置强 API Key，并在反向代理层限制来源。

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

## CORS

默认：

```bash
KOKORO_CORS_ORIGINS=http://localhost:8000
```

生产环境不要使用过宽的 CORS 来源。建议按域名明确配置：

```bash
KOKORO_CORS_ORIGINS=https://tts.example.com,https://app.example.com
```

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
