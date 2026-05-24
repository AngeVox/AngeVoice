# AngeVoice 后端接入指南（阅读器适配）

> 本文档面向 **AngeReader / Koodo / 自定义阅读器** 开发者，说明如何通过 AngeVoice TTS API 实现文本朗读、语音克隆和流式播放。

---

## 快速接入

### 1. 获取 TTS 能力

```bash
GET /v1/tts/capabilities
```

返回当前模型支持的编码格式、音色列表和音频参数：

```json
{
  "model": { "id": "kokoro", "formats": ["wav", "pcm", "mp3"] },
  "encodings": ["binary", "base64"],
  "voices": [
    {
      "id": "zm_010",
      "display_name": "中文男声 010",
      "gender": "male",
      "roles": ["male"]
    }
  ]
}
```

### 2. 基础 TTS 调用

```bash
POST /v1/audio/speech
Content-Type: application/json

{
  "model": "kokoro",
  "input": "要朗读的文本",
  "voice": "zm_010",
  "response_format": "wav",
  "response_encoding": "base64"
}
```

**参数说明：**

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `model` | string | 是 | `kokoro` 或 `moss-nano` |
| `input` | string | 是 | 待合成文本 |
| `voice` | string | 是 | 音色 ID（见 `/v1/tts/capabilities`） |
| `response_format` | string | 否 | `wav`（默认）、`mp3`、`pcm` |
| `response_encoding` | string | 否 | `binary`（默认，返回音频流）、`base64`（返回 JSON） |
| `speed` | float | 否 | 语速倍率，默认 1.0 |

### 3. Base64 响应格式

设置 `response_encoding=base64` 后返回 JSON：

```json
{
  "request_id": "...",
  "model": "kokoro",
  "voice": "zm_010",
  "response_format": "wav",
  "media_type": "audio/wav",
  "encoding": "base64",
  "audio": "<raw base64>",
  "audio_base64": "data:audio/wav;base64,<base64>",
  "sample_rate": 24000,
  "channels": 1,
  "bytes": 123456
}
```

> **WebView 播放提示：** 直接将 `audio_base64` 赋值给 `<audio>.src` 即可播放，无需额外解码。

### 4. 音色详情

```bash
GET /v1/audio/voices?detail=true
```

返回每个音色的性别和显示名，适合阅读器音色选择 UI：

```json
[
  {
    "id": "zm_010",
    "display_name": "中文男声 010",
    "gender": "male",
    "roles": ["male"]
  },
  {
    "id": "zf_010",
    "display_name": "中文女声 010",
    "gender": "female",
    "roles": ["female"]
  }
]
```

---

## MOSS 语音克隆

```bash
POST /api/tts
Content-Type: multipart/form-data

text=要朗读的文本
model=moss-nano
voice=custom
prompt_audio=@reference.wav
response_encoding=base64
```

克隆场景下 `prompt_audio` 传参考音频文件，服务端会自动提取说话人特征。

---

## 流式播放（WebSocket）

```bash
WS /ws/v1/tts
```

发送：

```json
{
  "model": "kokoro",
  "input": "长文本...",
  "voice": "zm_010",
  "format": "pcm"
}
```

服务端以小包推送音频片段，适合边下边播。

---

## 认证

如服务端启用了 `KOKORO_API_KEY`，所有请求需携带：

```
Authorization: Bearer <your-api-key>
```

---

## 常见问题

| 问题 | 解决方案 |
|---|---|
| 返回 401 | 检查 API Key 是否正确，Header 格式为 `Bearer <key>` |
| 音频无声 | 检查 `response_format` 是否与播放器兼容；PCM 需指定采样率 |
| 克隆音色不像 | 参考音频建议 5-15 秒、清晰无背景音 |
| 流式播放卡顿 | 尝试降低文本长度或切换 Kokoro 模型 |
