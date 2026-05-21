# v2.6.x 服务功能说明

v2.6.x 完成了服务端模块化重构、中文规则补强、Studio Web UI 刷新、安全启动校验、多模型运行时、MOSS 流式优化和持久化部署补齐，并统一项目品牌为 AngeVoice。批量合成、管理接口、可选 MP3、WebSocket 取消能力保持兼容。

> 文件名沿用历史路径，当前内容跟踪 v2.6.x。完整接口字段和调用示例见 [API 参考](API_REFERENCE.md)。

## v2.6.x 新增/调整

| 项目 | 说明 |
|---|---|
| 模块化服务端 | `server.py` 拆分为 `service_state.py`、`security.py`、`api_models.py`、`routes/*` |
| 多 worker 启动修复 | `KOKORO_WORKERS>1` 时使用 Uvicorn import string + factory 模式启动 |
| 并发缓存修复 | TTS LRU 缓存新增线程锁，避免多请求并发读写 `OrderedDict` |
| 中文规则 | 新增 `zh_rules.py`，支持自动停顿标点、jieba 分词优先和常见多音字上下文修正 |
| Studio Web UI | 前端拆分为 `templates/index.html`、`static/app.css`、`static/app.js`，支持亮/暗主题、API Key、流式播放、可折叠统计卡片、音色筛选/收藏 |
| 多模型运行时 | 新增 `engine_manager.py`，支持 Kokoro 与可选 MOSS-TTS-Nano 的加载、切换、卸载和缓存隔离 |
| MOSS-TTS-Nano | 通过 OpenMOSS 官方 ONNX runtime 接入，支持预设音色、参考音频克隆、CPU 基线和 CUDA 实验模式；Docker 画像预装匹配 runtime |
单引擎执行器 + 运行时锁，质量优先 MOSS 分包流式，参考音频裁剪与 prompt 代码 LRU 缓存，输出削峰/去脉冲/边缘淡化，降低克隆 OOM、爆音和重复编码开销|
| 输出持久化 | 新增 `ANGEVOICE_SAVE_OUTPUTS` / `ANGEVOICE_OUTPUT_DIR`，Docker 挂载 `outputs` 保存 HTTP 合成结果 |
| Docker 热更新修复 | Docker 镜像改为 editable install，Compose 挂载模板和 static 目录，CPU/GPU/老架构GPU 路径一致 |
| 安全启动校验 | 管理后台必须搭配 `ANGEVOICE_ADMIN_PASSWORD`；占位 API Key 会被拒绝；生产可用 `KOKORO_API_KEY=auto` 自动生成 |
| CLI 品牌统一 | 新增 `angevoice` 命令，保留 `kokoro-tts` alias |
| 发行包名 | `pyproject.toml` 项目名改为 `angevoice`，import 包名仍保留 `kokoro_tts` |
| 文档补强 | 新增架构、安全、排障文档，README 中英文重写 |
| CI 补强 | CLI smoke check 覆盖 `angevoice` 与 `kokoro-tts` |

## 功能总览

| 功能 | 接口/配置 | 默认状态 |
|---|---|---|
| OpenAI 兼容合成 | `POST /v1/audio/speech` | 开启 |
| 旧版兼容接口 | `POST/GET /api/tts` | 开启 |
| WebSocket 流式 | `GET /ws/v1/tts` | 开启 |
| 批量合成 ZIP | `POST /v1/audio/batch` | 开启 |
| 支持格式查询 | `GET /v1/audio/formats` | 开启 |
| 清理缓存 | `DELETE /admin/cache` | 管理接口关闭 |
| 查看音色目录 | `GET /admin/voices` | 管理接口关闭 |
| 上传 `.pt` 音色 | `POST /admin/voices/upload` | 上传关闭 |
| MP3 输出 | `response_format=mp3` | 关闭 |
| WebSocket 取消 | `{"type":"cancel"}` / `{"type":"stop"}` | 开启 |
| 模型管理 | `/v1/models` / `/v1/models/switch` | 开启 |
| MOSS 克隆 | `/api/tts` multipart `prompt_audio` | 选择支持克隆的 MOSS 模型后可用 |
| MOSS 克隆流式 | `/ws/v1/tts` 首包 `prompt_audio.data` | 选择支持克隆的 MOSS 模型后可用 |
| 输出持久化 | `ANGEVOICE_SAVE_OUTPUTS=true` | Docker Compose 默认开启 |

## 中文文本规则

`engine.normalize_text_for_tts()` 会在数字/单位规则后调用 `normalize_chinese_rules()`：

```text
春花秋月何时了 -> 默认不再替换为“瞭/蓼”，交给上游 G2P 和分词词典处理，避免在 MOSS/Kokoro 间读成奇怪音
我想了解一下 -> “了解”的“了”按 liǎo 处理
银行行长正在听音乐 -> 按上下文区分 háng/xíng、zhǎng/cháng、yuè/lè
会议12:43开始 -> 会议十二点四十三分开始
长中文无标点文本 -> 按词切分后补入停顿标点
```

分词优先使用 `jieba`，不可用时使用内置小词典兜底。多音字规则以短语和上下文匹配为主，明确场景会在内部替换为同音提示字来引导 G2P；对外 HTTP/WebSocket 仍接收正常文本。规则是保守增强，目标是减少常见朗读错误，不替代完整中文 NLP。

## Studio Web UI

新版 Web UI 保持零构建链，适合直接随 Python 包和 Docker 镜像分发：

- `/` 注入服务端 bootstrap 数据，包含音色、默认音色、采样率、认证和流式能力。
- `/static/app.css` 提供液态玻璃背景、亮/暗主题、启动动画、面板 spotlight/glare 效果。
- `/static/app.js` 负责 API Key、WebSocket 流式播放、HTTP 兜底合成、取消、统计和音色库交互。
- 所选模型支持 `voice_clone` 时才显示参考音频上传控件；HTTP 使用 multipart 上传，WebSocket 流式会在首包中携带参考音频 base64。
- 启用 `KOKORO_API_KEY` 后，前端可在设置面板保存 Bearer Token，并同时用于 HTTP 与 WebSocket 首包。

## 多模型与 MOSS

默认启动模型仍是 Kokoro。Docker 画像预装匹配的 MOSS runtime，但 MOSS 引擎和模型资产只在用户通过 Web UI/API 切换时加载。CPU 画像只开放 `moss-nano-cpu`；通用 GPU 画像默认开放 `moss-nano-cpu` 和 `moss-nano-cuda`；老架构GPU 镜像预装了 MOSS GPU 依赖，但默认隐藏 `moss-nano-cuda`。

```bash
ANGEVOICE_ENABLED_MODELS=kokoro,moss-nano-cpu
ANGEVOICE_DEFAULT_MODEL=kokoro
MOSS_CUDA_ENABLED=false
MOSS_MODEL_DIR=/app/models/MOSS-TTS-Nano-100M-ONNX
MOSS_PROMPT_AUDIO_MAX_SECONDS=8
MOSS_PROMPT_CACHE_MAX_ITEMS=8
MOSS_OUTPUT_PEAK_NORMALIZE_ENABLED=true
MOSS_REALTIME_STREAMING_DECODE=true
MOSS_OUTPUT_TARGET_PEAK=0.86
MOSS_OUTPUT_GAIN=0.94
MOSS_OUTPUT_DECLICK_ENABLED=true
MOSS_OUTPUT_EDGE_FADE_MS=1.5
```

MOSS 参考音频克隆示例：

```bash
curl -X POST http://localhost:8000/api/tts \
  -F model=moss-nano-cpu \
  -F text="这是参考音频克隆测试。" \
  -F voice=Junhao \
  -F response_format=wav \
  -F prompt_audio=@reference.wav \
  --output clone.wav
```

AngeVoice 中文规则默认也会作用到 MOSS：自动断句、时间读法、轻量语义匹配和常见多音字修正都会在进入模型前处理。Tesla P4 已通过 Docker 探针验证可使用通用 GPU 画像的 `onnxruntime-gpu==1.20.2` + `nvidia-cudnn-cu12==9.1.0.70` 跑通 MOSS CUDA 推理。缺 cuDNN 9 时会回退为 CPU session，AngeVoice 会拒绝该 CUDA 加载并按配置回退 CPU。

MOSS 克隆参考音频默认裁剪到 8 秒，并缓存编码后的 prompt audio codes。WebSocket 克隆默认启用逐帧流式以降低首包等待；如遇边界噪声或卡顿，可手动设置 `MOSS_REALTIME_STREAMING_DECODE=false` 回退到质量优先分包。

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
KOKORO_BATCH_CONCURRENCY=1
```

## 管理接口

管理后台/接口在 Docker 模板中默认开启，方便 NAS 用户首次进入后台查看/生成 API Key；默认凭据为 `admin` / `admin123`。公网部署必须改强密码，并建议同时设置 API Key：

```bash
KOKORO_ADMIN_ENABLED=true
ANGEVOICE_ADMIN_USERNAME=admin
ANGEVOICE_ADMIN_PASSWORD=admin123
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
- ../../models/models--hexgrad--Kokoro-82M-v1.1-zh/voices:/app/models/models--hexgrad--Kokoro-82M-v1.1-zh/voices:rw
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

服务端会停止后续段落推送，并在 `/requests` 中记录 `cancelled` 状态。当前段落如果已经进入同步推理，会在当前段完成后停止后续段。
