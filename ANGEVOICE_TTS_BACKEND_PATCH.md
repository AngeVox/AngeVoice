# AngeVoice TTS 后端接入能力补丁说明

本次修改目标是让 AngeVoice 更适合作为 AngeReader、Koodo Reader 二开版、WebView/PWA 阅读器、NAS 应用和其他前端项目的通用 TTS 后端框架。改动保持向后兼容：原有二进制音频流接口仍然可用，新增能力通过可选参数和新增接口暴露。

## 1. 新增能力总览

### 1.1 新增 `/v1/tts/capabilities`

用于让前端一次性发现当前 AngeVoice 服务支持的模型、格式、音色、流式、克隆、语速、情感字段预留等能力。

示例：

```bash
curl http://127.0.0.1:8101/v1/tts/capabilities
```

返回结构示例：

```json
{
  "service": "AngeVoice",
  "version": "2.6.5.3",
  "current_model": "kokoro",
  "auth_required": true,
  "formats": ["wav", "pcm"],
  "defaults": {
    "model": "kokoro",
    "voice": "zm_010",
    "speed": 1.0,
    "response_format": "wav"
  },
  "frontend_hints": {
    "preferred_response_encoding": "base64",
    "reader_role_types": ["narrator", "male", "female", "child", "unknown"],
    "emotion_fields_reserved": true
  },
  "models": []
}
```

前端建议用这个接口判断：

- 当前有哪些模型可用；
- 是否支持 `speed`；
- 是否支持参考音频克隆；
- 是否支持流式；
- 是否支持 MP3；
- 后续情感控制字段是否可以显示。

### 1.2 增强 `/v1/audio/voices`

原来的 `voices` 字符串数组保留，新增 `voice_details` 和 `capabilities`，方便阅读器直接生成音色选择 UI。

示例：

```bash
curl http://127.0.0.1:8101/v1/audio/voices?model=kokoro
curl http://127.0.0.1:8101/v1/audio/voices?model=kokoro\&detail=false
```

返回结构示例：

```json
{
  "model": "kokoro",
  "voices": ["zf_001", "zm_010"],
  "count": 2,
  "default_voice": "zm_010",
  "capabilities": {
    "supports_speed": true,
    "supports_clone": false,
    "supports_emotion": false,
    "formats": ["wav", "pcm"]
  },
  "voice_details": [
    {
      "id": "zf_001",
      "name": "zf_001",
      "display_name": "中文女声 001",
      "lang": "zh-CN",
      "gender": "female",
      "role_hints": ["female"],
      "provider": "angevoice",
      "backend": "kokoro",
      "model": "kokoro",
      "supports_speed": true,
      "supports_clone": false,
      "supports_emotion": false,
      "formats": ["wav", "pcm"]
    }
  ]
}
```

说明：

- `voices` 保持旧格式，避免破坏旧客户端；
- `voice_details` 给 AngeReader/Koodo 二开使用；
- Kokoro 音色根据 `zf_*` / `zm_*` 做了女声/男声启发式标记；
- MOSS 音色性别默认 `unknown`，避免误判；
- `role_hints` 可以辅助阅读器把音色映射到旁白、男声、女声、儿童等角色。

### 1.3 `/v1/audio/speech` 支持 `response_encoding=base64`

原有 OpenAI 兼容接口默认仍返回音频字节流；新增可选参数 `response_encoding`，方便 WebView、PWA、阅读器前端直接拿 JSON 缓存和播放。

二进制旧行为：

```bash
curl -X POST http://127.0.0.1:8101/v1/audio/speech \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer YOUR_TOKEN' \
  -d '{"model":"kokoro","input":"你好世界","voice":"zm_010"}' \
  --output out.wav
```

新增 JSON/base64：

```bash
curl -X POST http://127.0.0.1:8101/v1/audio/speech \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer YOUR_TOKEN' \
  -d '{"model":"kokoro","input":"你好世界","voice":"zm_010","response_encoding":"base64"}'
```

返回结构示例：

```json
{
  "request_id": "xxxxxx",
  "model": "kokoro",
  "voice": "zm_010",
  "response_format": "wav",
  "media_type": "audio/wav",
  "encoding": "base64",
  "audio_base64": "data:audio/wav;base64,...",
  "data_url": "data:audio/wav;base64,...",
  "audio": "...纯 base64...",
  "bytes": 12345,
  "sample_rate": 24000,
  "channels": 1
}
```

### 1.4 `/api/tts` 同步支持 `response_encoding=base64`

旧版 `/api/tts` 的 JSON、form、GET 调用也支持：

```bash
curl --get http://127.0.0.1:8101/api/tts \
  -H 'Authorization: Bearer YOUR_TOKEN' \
  --data-urlencode 'text=你好世界' \
  --data-urlencode 'voice=zm_010' \
  --data-urlencode 'response_encoding=base64'
```

### 1.5 情感和风格字段预留

`/v1/audio/speech` 的请求模型新增以下预留字段：

```json
{
  "emotion": "sad",
  "emotion_strength": 0.6,
  "style_prompt": "低声、温柔、略带克制"
}
```

当前 Kokoro 和 MOSS 不会真正消费这些字段，后续接 CosyVoice、IndexTTS2、阿里云等支持情感或风格提示的 Provider 时，可以在不破坏前端协议的前提下继续扩展。

## 2. 修改过的文件

```text
src/kokoro_tts/api_models.py
src/kokoro_tts/routes/audio.py
src/kokoro_tts/routes/status.py
tests/test_docker_integration.py
```

## 3. 兼容性说明

- 原有 `/v1/audio/speech` 默认仍返回 `audio/wav` 字节流；
- 原有 `/api/tts` 默认仍返回音频字节流；
- `/v1/audio/voices` 的 `voices` 字段仍是字符串数组；
- 新增字段只会增加响应内容，不会移除旧字段；
- `response_encoding` 默认为 `binary`，旧客户端无感。

## 4. AngeReader 接入建议

AngeReader 第一版建议按这个流程接入：

```text
1. 启动时请求 /v1/tts/capabilities
2. 根据 models[].supports_speed / supports_clone / supports_emotion 决定 UI 显示
3. 请求 /v1/audio/voices?model=kokoro 获取 voice_details
4. 把 narrator / male / female / child 映射到 voice_details 里的音色
5. 合成时调用 /v1/audio/speech，并使用 response_encoding=base64
6. 前端直接播放 audio_base64 或 data_url
```

## 5. 已验证项目

已执行：

```bash
PYTHONPATH=src pytest -q tests/test_docker_integration.py -q
python -m py_compile src/kokoro_tts/api_models.py src/kokoro_tts/routes/audio.py src/kokoro_tts/routes/status.py
```

结果：`tests/test_docker_integration.py` 全部通过。
