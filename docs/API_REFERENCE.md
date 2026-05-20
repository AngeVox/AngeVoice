# API 参考

本文档是 AngeVoice v2.6.x 的 API 参考手册，涵盖 Studio Web UI、可复制示例页面 `/api-docs`、OpenAI 兼容 HTTP 合成、旧版 `/api/tts` 接口、模型切换、MOSS-TTS-Nano 参考音频克隆、WebSocket 流式合成、批量导出及可选管理接口。

## 调用地址

| 部署方式 | HTTP / Web UI | WebSocket |
|---|---|---|
| pip / 开发环境 | `http://localhost:8000` | `ws://localhost:8000/ws/v1/tts` |
| Docker CPU | `http://localhost:8100` | `ws://localhost:8100/ws/v1/tts` |
| Docker GPU | `http://localhost:8101` | `ws://localhost:8101/ws/v1/tts` |
| Docker 旧架构 GPU | `http://localhost:8102` | `ws://localhost:8102/ws/v1/tts` |

以下示例均使用：

```bash
BASE_URL=http://localhost:8000
WS_URL=ws://localhost:8000/ws/v1/tts
```

Docker 部署时只需替换端口号。远程 NAS 部署时把 `localhost` 换成 NAS 主机名或 IP，例如 `http://192.168.1.2:8101`。

## 文档页面

| 路径 | 用途 |
|---|---|
| `/` | Studio Web UI |
| `/api-docs` | 普通用户可复制示例页面，重点说明 MOSS 克隆 |
| `/docs` | FastAPI Swagger UI |
| `/redoc` | FastAPI ReDoc |

## 鉴权

当 `KOKORO_API_KEY` 为空时，本地可信部署无需 token 即可调用接口。当设置了 API key 后，HTTP 请求需要携带：

```bash
-H "Authorization: Bearer YOUR_TOKEN"
```

WebSocket 客户端可通过 `Authorization` 头或首条 JSON 消息传递 token：

```json
{
  "text": "你好世界",
  "voice": "zm_010",
  "token": "YOUR_TOKEN"
}
```

内置 Studio Web UI 会在设置面板保存 Bearer Token，同时用于 HTTP 请求和 WebSocket 首包。

## 接口列表

| 方法 | 路径 | 说明 | 鉴权 |
|---|---|---|---|
| `GET` | `/` | Studio Web UI | 否 |
| `GET` | `/api-docs` | 可复制示例文档页 | 否 |
| `GET` | `/health` | 服务健康状态、当前模型、音色列表、流式能力 | 否 |
| `GET` | `/stats` | 运行时指标快照 | 设置 API key 后需要 |
| `GET` | `/requests` | 最近请求状态 | 设置 API key 后需要 |
| `GET` | `/v1/models` | 已启用模型列表及当前模型 | 否 |
| `GET` | `/v1/models/current` | 当前模型元信息 | 否 |
| `POST` | `/v1/models/switch` | 加载并切换当前模型 | 需要 |
| `POST` | `/v1/models/{model_id}/load` | 预热加载模型 | 需要 |
| `POST` | `/v1/models/{model_id}/unload` | 卸载已加载模型 | 需要 |
| `GET` | `/v1/audio/voices` | 音色列表，支持 `?model=` 参数 | 否 |
| `GET` | `/v1/audio/formats` | 支持的输出格式列表 | 否 |
| `POST` | `/v1/audio/speech` | OpenAI 兼容语音合成 | 设置 API key 后需要 |
| `GET` | `/api/tts` | 旧版 query-string 语音合成 | 设置 API key 后需要 |
| `POST` | `/api/tts` | 旧版 JSON/表单语音合成；multipart 支持 MOSS 克隆上传 | 设置 API key 后需要 |
| `WS` | `/ws/v1/tts` | WebSocket 流式合成；首条消息携带请求参数 | 设置 API key 后需要 |
| `POST` | `/v1/audio/batch` | 批量合成 ZIP，返回 `manifest.json` | 设置 API key 后需要 |
| `POST` | `/v1/audio/requests/{request_id}/cancel` | 标记正在执行的请求为取消状态 | 设置 API key 后需要 |
| `DELETE` | `/admin/cache` | 清空内存中的合成缓存 | 需开启 Admin，使用管理员账号密码或 Bearer Token |
| `GET` | `/admin/voices` | 查看本地 Kokoro 音色目录 | 需开启 Admin，使用管理员账号密码或 Bearer Token |
| `POST` | `/admin/voices/upload` | 上传可信的 `.pt` Kokoro 音色文件 | 需开启 Admin + 上传功能，使用管理员账号密码或 Bearer Token |


### `/health` status 字段

| status | 说明 |
|---|---|
| `ok` | 服务正常，当前模型已加载 |
| `idle` | 服务正常，当前模型因空闲超时已卸载；下次请求自动加载 |
| `loading` | 服务已启动但当前模型正在首次加载或尚未加载完成 |
| `degraded` | 至少有一个已加载模型 unhealthy |

Docker 健康检查将 `ok` 和 `idle` 都视为可用状态。

## 模型 ID

| 模型 ID | 说明 | 克隆支持 |
|---|---|---|
| `kokoro` | Kokoro v1.1 中文引擎，默认启动 | 不支持；使用 Kokoro `.pt` 音色 |
| `moss-nano-cpu` | MOSS-TTS-Nano ONNX，CPU 推理 | 支持 |
| `moss-nano-cuda` | MOSS-TTS-Nano ONNX，CUDA 推理 | 支持（实验性） |

别名 `moss` 和 `moss-nano` 根据 `MOSS_EXECUTION_PROVIDER` 环境变量自动解析。CPU 和旧架构部署默认隐藏 `moss-nano-cuda`。

## 状态查询与发现

```bash
curl "$BASE_URL/health"
curl "$BASE_URL/stats"
curl "$BASE_URL/requests"
curl "$BASE_URL/v1/audio/formats"
```

查询音色列表（当前模型或指定模型）：

```bash
curl "$BASE_URL/v1/audio/voices"
curl "$BASE_URL/v1/audio/voices?model=moss-nano-cpu"
```

模型加载、切换与卸载：

```bash
curl "$BASE_URL/v1/models"
curl "$BASE_URL/v1/models/current"

curl -X POST "$BASE_URL/v1/models/moss-nano-cpu/load" \
  -H "Authorization: Bearer YOUR_TOKEN"

curl -X POST "$BASE_URL/v1/models/switch" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{"model":"moss-nano-cpu","unload_previous":true}'

curl -X POST "$BASE_URL/v1/models/moss-nano-cpu/unload" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

设置 `unload_previous=true` 会在切换模型后释放旧引擎并清空音频缓存。GPU/NAS 部署推荐使用此选项。

## OpenAI 兼容合成

接口地址：

```http
POST /v1/audio/speech
Content-Type: application/json
```

请求参数：

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `model` | string | `kokoro` | `kokoro`、`moss-nano-cpu`、`moss-nano-cuda` 或别名 |
| `input` | string | 必填 | 待合成文本，`text` 也可作为别名 |
| `voice` | string | 模型默认 | Kokoro 音色 ID 或 MOSS 预设音色 |
| `speed` | number | `1.0` | 范围 `0.5` 到 `2.0`；MOSS 暂不支持语速调节，使用 MOSS 时必须为 `1.0`，否则返回 400 |
| `response_format` | string | `wav` | 可选 `wav`、`pcm`、`mp3`（需开启） |

Kokoro 示例：

```bash
curl -X POST "$BASE_URL/v1/audio/speech" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{"model":"kokoro","input":"你好世界","voice":"zm_010","speed":1.0,"response_format":"wav"}' \
  --output kokoro.wav
```

MOSS 预设音色示例：

```bash
curl -X POST "$BASE_URL/v1/audio/speech" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{"model":"moss-nano-cpu","input":"派大星，我们一起去抓水母吧。","voice":"Junhao","response_format":"wav"}' \
  --output moss.wav
```

响应说明：

- 响应体为音频字节流
- `Content-Type` 为 `audio/wav`、`audio/pcm` 或 MP3 时为 `audio/mpeg`
- 响应头包含 `X-Request-ID`

> `/v1/audio/speech` 仅支持 JSON 格式。如需 MOSS 参考音频克隆上传，请使用 `/api/tts` 的 multipart 方式。

## 旧版 `/api/tts` 接口

`/api/tts` 支持 JSON、query-string 和表单数据三种格式。当需要上传 MOSS 参考音频进行克隆时，需使用此接口（multipart 上传不在 OpenAI 兼容 JSON 格式范围内）。

JSON 请求：

```bash
curl -X POST "$BASE_URL/api/tts" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{"model":"kokoro","text":"你好世界","voice":"zm_010","format":"wav"}' \
  --output output.wav
```

Query-string 请求：

```bash
curl --get "$BASE_URL/api/tts" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  --data-urlencode "text=你好世界" \
  --data-urlencode "voice=zm_010" \
  --data-urlencode "response_format=wav" \
  --output output.wav
```

Multipart 请求（不含克隆）：

```bash
curl -X POST "$BASE_URL/api/tts" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F model=kokoro \
  -F text="你好世界" \
  -F voice=zm_010 \
  -F response_format=wav \
  --output output.wav
```

## MOSS 参考音频克隆

### 参考音频存放位置

MOSS 参考音频**不是** Kokoro 音色文件，不要放到 `models/voices` 目录。`models/voices` 仅用于存放 Kokoro 的 `.pt` 音色文件。

| 使用方式 | 音频存放位置 | 适用场景 |
|---|---|---|
| HTTP multipart 上传 | 客户端本地文件，例如 `./reference.wav`，通过 `-F prompt_audio=@reference.wav` 上传 | 最常用；每次请求携带一个参考文件 |
| WebSocket base64 | 客户端读取本地文件后以 base64/data URL 发送，放在首条 JSON 消息的 `prompt_audio.data` 字段 | 流式克隆、浏览器上传、实时播放 |
| 服务端默认 prompt | 将文件挂载到容器内，例如 `/app/prompts/reference.wav`，并设置 `MOSS_PROMPT_AUDIO_PATH` | 固定使用同一个克隆音色，无需每次上传 |

参考音频建议：

- 时长 3-10 秒
- 单人说话
- 语音清晰，背景噪音低
- 避免过长的音乐或嘈杂片段

相关环境变量：

| 变量 | 用途 |
|---|---|
| `MOSS_PROMPT_UPLOAD_MAX_BYTES` | 上传文件大小限制 |
| `MOSS_PROMPT_AUDIO_MAX_SECONDS` | prompt 编码前的截断时长 |
| `MOSS_PROMPT_CACHE_MAX_ITEMS` | 缓存已编码的 prompt 码，用于重复克隆请求 |

### HTTP multipart 克隆

```bash
curl -X POST "$BASE_URL/api/tts" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F model=moss-nano-cpu \
  -F text="这是参考音频克隆测试。" \
  -F voice=Junhao \
  -F response_format=wav \
  -F prompt_audio=@reference.wav \
  --output clone.wav
```

字段别名：

| 字段 | 别名 | 说明 |
|---|---|---|
| `prompt_audio` | `reference_audio` | multipart 上传字段 |
| `response_format` | `format` | 输出格式：`wav`、`pcm`、`mp3`（需开启） |
| `text` | `input`、`prompt` | `/api/tts` 的文本字段 |
| `voice` | `speaker` | `/api/tts` 的音色字段 |

将 `prompt_audio` 上传到 `kokoro` 或其他不支持克隆的模型时，返回 `400 当前模型不支持参考音频克隆`。

### Python HTTP 上传克隆示例

```python
import requests

base_url = "http://localhost:8000"
headers = {"Authorization": "Bearer YOUR_TOKEN"}

with open("reference.wav", "rb") as audio:
    files = {"prompt_audio": ("reference.wav", audio, "audio/wav")}
    data = {
        "model": "moss-nano-cpu",
        "text": "这是 Python 上传参考音频克隆测试。",
        "voice": "Junhao",
        "response_format": "wav",
    }
    resp = requests.post(f"{base_url}/api/tts", headers=headers, data=data, files=files)
    resp.raise_for_status()

with open("clone.wav", "wb") as out:
    out.write(resp.content)
```

### 服务端默认参考音频

如果所有 MOSS 克隆请求都使用同一段参考音频，可以将其挂载到容器内并设置 `MOSS_PROMPT_AUDIO_PATH`。

Docker Compose 示例：

```yaml
volumes:
  - ../../prompts:/app/prompts:ro

environment:
  - MOSS_PROMPT_AUDIO_PATH=/app/prompts/reference.wav
  - MOSS_PROMPT_AUDIO_MAX_SECONDS=8
  - MOSS_PROMPT_CACHE_MAX_ITEMS=8
```

之后调用 `/api/tts` 时无需传 `prompt_audio` 字段：

```bash
curl -X POST "$BASE_URL/api/tts" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F model=moss-nano-cpu \
  -F text="这次请求会使用服务端默认参考音频。" \
  -F voice=Junhao \
  -F response_format=wav \
  --output clone-default.wav
```

> 注意：这不会生成 Kokoro `.pt` 音色文件，只是为 MOSS 提供一条可复用的 prompt audio 路径。

## WebSocket 流式合成

连接地址：

```text
ws://localhost:8000/ws/v1/tts
```

首条 JSON 消息参数：

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `model` | string | 当前默认模型 | 可选，指定模型 ID |
| `text` | string | 必填 | 待合成文本 |
| `voice` | string | 模型默认音色 | Kokoro 音色 ID 或 MOSS 预设 |
| `speed` | number | 配置默认值 | 范围 `0.5` 到 `2.0`；MOSS 暂不支持语速调节，使用 MOSS 时必须为 `1.0`，否则返回 400 |
| `format` | string | `pcm_s16le` | 可选 `pcm_s16le` 或 `wav` |
| `binary` | boolean | `false` | 启用后发送二进制音频帧（需满足条件） |
| `token` | string | 空 | 启用 API key 时需传递 |
| `prompt_audio.data` | string | 空 | MOSS 克隆流式的 base64 或 data URL |
| `prompt_audio.filename` | string | `prompt.wav` | 用于后缀校验 |

### 基础浏览器流式示例

```javascript
const ws = new WebSocket("ws://localhost:8000/ws/v1/tts");

ws.onopen = () => {
  ws.send(JSON.stringify({
    model: "kokoro",
    text: "你好世界，这是一段流式合成测试。",
    voice: "zm_010",
    speed: 1.0,
    format: "pcm_s16le",
    binary: false,
    token: "YOUR_TOKEN"
  }));
};

ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  if (msg.type === "audio") {
    const pcmBytes = Uint8Array.from(atob(msg.data), (c) => c.charCodeAt(0));
    // 将 pcmBytes 送入 AudioWorklet、WebAudio buffer 或播放队列
  }
};

ws.send(JSON.stringify({ type: "cancel" }));
```

### MOSS 克隆流式首包

```json
{
  "model": "moss-nano-cpu",
  "text": "这是参考音频克隆的流式测试。",
  "voice": "Junhao",
  "format": "pcm_s16le",
  "binary": false,
  "prompt_audio": {
    "filename": "reference.wav",
    "data": "<base64-or-data-url>"
  },
  "token": "YOUR_TOKEN"
}
```

为兼容旧版自定义客户端，也接受 `prompt_audio_data`、`reference_audio_data` 和 `prompt_audio_filename` 字段。

### 浏览器 FileReader 克隆流式

```javascript
async function fileToDataUrl(file) {
  return await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

async function startMossCloneStream(file) {
  const promptData = await fileToDataUrl(file);
  const ws = new WebSocket("ws://localhost:8000/ws/v1/tts");

  ws.onopen = () => {
    ws.send(JSON.stringify({
      model: "moss-nano-cpu",
      text: "这是网页端 MOSS 克隆流式测试。",
      voice: "Junhao",
      format: "pcm_s16le",
      binary: false,
      token: "YOUR_TOKEN",
      prompt_audio: {
        filename: file.name || "reference.wav",
        data: promptData
      }
    }));
  };

  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.type === "audio") {
      const bytes = Uint8Array.from(atob(msg.data), c => c.charCodeAt(0));
      // bytes 为 PCM s16le 数据，送入 AudioWorklet/播放队列，或在客户端封装为 WAV
      console.log("audio chunk", bytes.byteLength);
    }
    if (msg.type === "done") ws.close();
    if (msg.type === "error" || msg.type === "segment_error") {
      console.error(msg.message);
    }
  };

  return ws;
}
```

### Python WebSocket 克隆流式示例

```python
import asyncio
import base64
import json
import websockets

async def main():
    with open("reference.wav", "rb") as f:
        prompt_b64 = base64.b64encode(f.read()).decode("ascii")

    async with websockets.connect("ws://localhost:8000/ws/v1/tts") as ws:
        await ws.send(json.dumps({
            "model": "moss-nano-cpu",
            "text": "这是 Python WebSocket 克隆流式测试。",
            "voice": "Junhao",
            "format": "pcm_s16le",
            "binary": False,
            "token": "YOUR_TOKEN",
            "prompt_audio": {
                "filename": "reference.wav",
                "data": prompt_b64
            }
        }, ensure_ascii=False))

        with open("stream.pcm", "wb") as out:
            async for raw in ws:
                msg = json.loads(raw)
                if msg.get("type") == "audio":
                    out.write(base64.b64decode(msg["data"]))
                elif msg.get("type") in {"done", "cancelled"}:
                    break
                elif msg.get("type") in {"error", "segment_error"}:
                    raise RuntimeError(msg.get("message"))

asyncio.run(main())
```

上面的示例保存的是原始 PCM s16le 数据。如需直接得到 WAV 文件，可请求 `format:"wav"`，或根据返回的 `sample_rate`、`channels` 自行封装。

服务端消息类型：

| 类型 | 含义 |
|---|---|
| `started` | 流元信息：`segments`、`sample_rate`、`channels`、`format`、`dtype`，可选 `voice_clone` |
| `audio` | 音频块：`index`、可选 `segment_index`、`data`、`format`、`sample_rate`、`channels`、`request_id`、`model` |
| `segment_error` | 某个分段合成失败，但流可能继续或正常结束 |
| `done` | 合成完成，包含 `total_segments` 和 `total_audio_chunks` |
| `cancelled` | 客户端发送了 `cancel`/`stop`，或请求被标记为取消 |
| `error` | 请求级错误 |

二进制模式下，`audio` 消息的 JSON 部分不包含 `data` 字段，随后紧跟原始音频字节。JSON 模式始终在 `data` 字段中以 base64 编码传输。

## 批量 ZIP 合成

接口地址：

```http
POST /v1/audio/batch
Content-Type: application/json
```

示例：

```bash
curl -X POST "$BASE_URL/v1/audio/batch" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "model":"kokoro",
    "voice":"zm_010",
    "speed":1.0,
    "response_format":"wav",
    "items":[
      {"text":"第一段","filename":"001"},
      {"text":"第二段","filename":"002","voice":"zf_001"},
      {"model":"moss-nano-cpu","text":"第三段使用 MOSS。","voice":"Junhao","filename":"003"}
    ]
  }' \
  --output angevoice_batch.zip
```

响应为 `application/zip` 格式，包含：

- 每个成功项生成一个音频文件
- `manifest.json` 记录每项的状态、文件名、字节数或错误信息

批量项可单独覆盖 `model`、`voice`、`speed` 和 `filename`。批量接口不支持克隆上传，MOSS 参考音频克隆请使用 `/api/tts` multipart 方式。

## 取消请求

HTTP 请求返回的响应头包含 `X-Request-ID`，WebSocket 消息中包含 `request_id`。取消正在执行的请求：

```bash
curl -X POST "$BASE_URL/v1/audio/requests/REQUEST_ID/cancel" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

WebSocket 客户端也可发送：

```json
{"type":"stop"}
```

或：

```json
{"type":"cancel"}
```

取消操作会阻止后续分段的推送。如果当前分段已进入同步推理阶段，通常会在该分段完成后停止。

## 可选管理接口

管理接口在 Docker 模板中默认开启，便于 NAS 用户首次进入后台查看/生成 API Key；默认凭据为 `admin` / `admin123`。公网部署必须改强密码，仅在可信环境中启用：

```bash
KOKORO_ADMIN_ENABLED=true
ANGEVOICE_ADMIN_USERNAME=admin
ANGEVOICE_ADMIN_PASSWORD=admin123
```

清空缓存：

```bash
curl -X DELETE "$BASE_URL/admin/cache" \
  -u "admin:YOUR_ADMIN_PASSWORD"
```

查看本地 Kokoro 音色：

```bash
curl "$BASE_URL/admin/voices" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

上传可信 `.pt` 音色文件：

```bash
curl -X POST "$BASE_URL/admin/voices/upload" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F file=@my_voice.pt
```

音色上传还需启用：

```bash
KOKORO_VOICE_UPLOAD_ENABLED=true
```

 > 请勿将 `/admin/*` 接口暴露到公网。

⚠️ **安全警告 / Security Warning**：公网环境**不建议**开启 `KOKORO_VOICE_UPLOAD_ENABLED`。
仅允许上传自己生成或完全可信来源的 `.pt` 文件。
如果必须开放，建议只在内网管理端使用，并配合反代 IP 白名单。
`.pt` 文件是 PyTorch 序列化格式，理论上可执行任意代码。

不建议在公网暴露的服务上启用 `KOKORO_VOICE_UPLOAD_ENABLED`，除非你已在反向代理层做严格鉴权与来源限制。
Only upload `.pt` files you generated yourself or from fully trusted sources.
If upload must be enabled, restrict to internal network admin endpoints with reverse-proxy IP whitelisting.
`.pt` files use PyTorch serialization which can theoretically execute arbitrary code.

## 输出格式

| 格式 | 请求值 | 响应 Content-Type |
|---|---|---|
| WAV | `wav` | `audio/wav` |
| PCM s16le | HTTP: `pcm`；WebSocket: `pcm_s16le` | 原始 PCM 字节流 |
| MP3 | `mp3` | `audio/mpeg`；需设置 `KOKORO_MP3_ENABLED=true` 且安装 ffmpeg |

可通过 `GET /v1/audio/formats` 查询当前是否启用 MP3 以及容器中是否安装了 ffmpeg。

## 流式解码参数配置

以下环境变量控制 WebSocket 流式合成中的分段解码策略，适用于需要精细调节合成延迟和内存占用的场景。

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `ANGEVOICE_RUNTIME_CONFIG_FILE` | `/app/outputs/runtime-config.json` | Admin 后台保存配置的位置；在环境变量之后加载，可导出 ENV patch |
| `MOSS_REALTIME_STREAMING_DECODE` | `true` | 是否启用 MOSS 官方逐帧实时解码；默认开启以降低首包等待；如出现电流音/卡顿可改为 `false` 走质量优先整块生成后分包 |
| `MOSS_SEGMENT_LENGTH` | `120` | MOSS 专用分段长度，减少中英文混合尾部漂移、卡顿和失真；不影响 Kokoro 的 `KOKORO_SEGMENT_LENGTH` |
| `MOSS_MIXED_ENGLISH_POLICY` | `translate` | MOSS 中英文混排策略；默认把常见英文词组转成自然中文，减少长停顿、怪声和尾部漂移；可设为 `preserve` 保留英文 |
| `KOKORO_TRUST_PROXY_HEADERS` | `false` | 是否信任 `X-Forwarded-For`/`X-Real-IP`；裸露公网保持 false，反代后确认可信再开启 |
| `KOKORO_ADMIN_ALLOW_API_KEY` | `false` | 是否允许普通 Bearer API Key 登录管理后台；共享 API Key 给客户端时保持 false |
| `KOKORO_PUBLIC_STATUS_ENDPOINTS` | `true` | 是否公开 `/v1/models`、`/v1/models/current`、`/v1/audio/voices` 和页面模型目录 bootstrap；设为 false 后目录接口需要 Bearer Token，`/health` 仅返回最小健康信息 |
| `MOSS_STREAM_BUDGET_THRESHOLD_LOW` | `0.25` | 音频播放余量低阈值（秒）：低于此值每次只解码 1 帧，优先保证点生成后尽快出声 |
| `MOSS_STREAM_BUDGET_THRESHOLD_MID` | `0.65` | 音频播放余量中阈值（秒）：低于此值每次解码 2 帧 |
| `MOSS_STREAM_BUDGET_THRESHOLD_HIGH` | `1.20` | 音频播放余量高阈值（秒）：低于此值每次解码 4 帧，高于此值每次解码 8 帧以减少块间抖动 |
| `MOSS_STREAM_CHUNK_MIN_FLOOR` | `0.10` | 最小流式分包时长下限（秒）：防止过短碎片导致听感卡顿 |
| `MOSS_OUTPUT_DECLICK_ENABLED` | `true` | 是否启用 MOSS 孤立脉冲修复 |
| `MOSS_OUTPUT_EDGE_FADE_MS` | `1.5` | MOSS 片段边缘淡入淡出毫秒数，减少爆音但避免过度抹平辅音 |
| `MOSS_APPLY_ANGEVOICE_RULES` | `auto` | MOSS 文本规则：`auto` 中文为主走完整规则，中英文/技术文本保守处理；`true` 强制完整规则；`false` 仅温和清理 |
| `MOSS_VRAM_SNAPSHOT_TTL_SECONDS` | `10` | MOSS 显存快照缓存 TTL（秒），避免流式过程中频繁 torch.cuda/nvidia-smi 查询造成同步卡顿；0=每次查询 |

这三个阈值（`LOW` < `MID` < `HIGH`）不是显存占用比例，而是“已生成音频领先实时播放的秒数”。余量越少，解码越小块，优先降低首包延迟；余量越充足，解码块越大，减少块间抖动。

## 空闲超时自动释放显存

在 GPU 部署场景中，多模型共存会占用大量显存。启用空闲超时后，所有已加载模型（包括当前选中的模型）在空闲一段时间后会被自动卸载以释放显存/内存，下次请求时再自动重新加载，对调用方完全透明。

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `ANGEVOICE_IDLE_TIMEOUT_SECONDS` | `600` | 空闲超时时间（秒）。模型在连续 N 秒内没有收到请求时自动卸载。设置为 `0` 表示禁用此功能 |
| `ANGEVOICE_IDLE_CHECK_INTERVAL` | `30` | 检查间隔（秒）。系统每隔 N 秒检查一次各模型的空闲状态 |

工作原理：

1. 系统每隔 `ANGEVOICE_IDLE_CHECK_INTERVAL` 秒检查一次各模型的最后请求时间
2. 如果某个已加载模型已空闲超过 `ANGEVOICE_IDLE_TIMEOUT_SECONDS` 秒，自动调用卸载
3. 下一次对该模型发起的 API 请求会先触发重新加载，加载完成后正常返回合成结果
4. 默认也会释放当前活跃模型；如需保持当前模型常驻，可设置 `ANGEVOICE_IDLE_UNLOAD_CURRENT=false`

推荐配置：

```bash
# 30 分钟无请求自动释放显存，每 30 秒检查一次
ANGEVOICE_IDLE_TIMEOUT_SECONDS=1800
ANGEVOICE_IDLE_CHECK_INTERVAL=30
```

> 注意：重新加载模型需要一定时间（通常几秒到十几秒），首次请求的延迟会略高。如果显存/内存充裕，可以设置 `ANGEVOICE_IDLE_TIMEOUT_SECONDS=0` 禁用空闲卸载。

## 常见错误

| 错误现象 | 原因 | 处理方式 |
|---|---|---|
| `当前模型不支持参考音频克隆` | 请求使用了 `kokoro` 或其他不支持克隆的模型 | 切换到 `moss-nano-cpu` 或 `moss-nano-cuda` |
| MOSS 模型不可用 | 未安装运行时或模型被部署配置隐藏 | 检查 `/v1/models`、`ANGEVOICE_ENABLED_MODELS`、`MOSS_CUDA_ENABLED` |
| WebSocket 已连接但无音频 | 首条消息缺少必要字段、token 错误或代理未正确转发 WebSocket | 先直接测试 `ws://host:port/ws/v1/tts`，再排查代理配置 |
| 克隆合成出现 OOM / 爆音 / 失真 | prompt 过长、CUDA provider 不稳定、显存不足 | 降低 `MOSS_PROMPT_AUDIO_MAX_SECONDS` 至 5-8，或改用 `moss-nano-cpu` 测试 |
| `401 Unauthorized` | 已配置 `KOKORO_API_KEY` 但请求未携带 token | 在请求头添加 Bearer token，或在 WebSocket 首包中添加 `token` 字段 |

| `MOSS_PROCESS_ISOLATION_ENABLED` | `false` | 是否启用 MOSS 进程级隔离；默认关闭；低配/老机器建议保持关闭，它只影响隔离 worker，不影响质量优先流式分包 |
| `MOSS_PROCESS_ISOLATION_PROVIDERS` | `cuda` | 哪些 provider 使用隔离子进程 |
| `MOSS_PROCESS_KILL_GRACE_SECONDS` | `2` | worker 超时后终止/强杀的宽限秒数 |

### 管理后台页面

浏览器访问：

```text
GET /admin
```

开启方式：

```bash
KOKORO_ADMIN_ENABLED=true
ANGEVOICE_ADMIN_USERNAME=admin
ANGEVOICE_ADMIN_PASSWORD=admin123
```

`/admin` 使用 HTTP Basic 登录。账号和密码支持中文；服务端会兼容 UTF-8 与 latin-1 Basic Auth 编码，避免不同浏览器编码差异导致无法进入后台。

管理页面提供五个区块：

- Dashboard：当前模型、缓存、请求、音频质量概览。
- Models：加载、切换、释放、强制释放模型。
- Tuning：MOSS 长文本、流式、静音压缩、crossfade、峰值保护等参数；内置 NAS 稳定、长文本旁白、低延迟流式、克隆质量优先四个预设。
- Security：API Key 状态、查看和轮换。
- Diagnostics：最近请求、last_output_quality、ENV patch 和折叠的原始 JSON。

后台保存配置会写入 `ANGEVOICE_RUNTIME_CONFIG_FILE`，默认 `/app/outputs/runtime-config.json`。启动加载顺序是代码默认值、环境变量、runtime-config，所以上次在后台保存的值会在重启后继续生效。页面也可以导出 ENV patch，方便把最终参数固化到 `.env`。

常用 Admin API：

| 方法 | 路径 | 用途 |
|---|---|---|
| `GET` | `/admin/api/status` | 后台总状态 |
| `GET` | `/admin/api/config` | 当前可编辑配置、schema、ENV patch |
| `GET` | `/admin/api/config/schema` | 配置 schema 和预设 |
| `PATCH` | `/admin/api/config` | 保存运行时配置 |
| `POST` | `/admin/api/config/profile` | 应用预设 |
| `GET` | `/admin/api/config/env` | 导出 ENV patch |
