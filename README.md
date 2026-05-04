# Kokoro TTS 中文语音合成

> 基于 [Kokoro v1.1](https://huggingface.co/hexgrad/Kokoro-82M) 的轻量级中文 TTS 服务，支持 OpenAI 兼容 API、WebSocket 逐段流式、批量合成、缓存与 Docker 部署。

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

## 特性

- **中英双语** — 中文 pipeline + 英文 G2P 回调，支持中英文混合输入
- **OpenAI 兼容 API** — 支持 `/v1/audio/speech`，兼容 `model/input/voice/speed/response_format`
- **逐段流式合成** — WebSocket 按文本段落推送音频，支持 JSON/base64 与 binary 音频帧
- **服务化能力** — 内存 LRU 缓存、请求 ID、请求状态、`/stats`、`/requests`、超时控制
- **批量合成** — `/v1/audio/batch` 可批量生成 ZIP，适合有声书和分段配音
- **管理接口** — 可选开启缓存清理、音色列表、`.pt` 音色上传
- **可选 MP3** — 默认 WAV/PCM，开启 `KOKORO_MP3_ENABLED=true` 后支持 MP3 转码
- **Docker 部署** — CPU/GPU Compose 模板内置常用环境变量和调试注释
- **部署画像** — 通用服务版与老显卡/保守兼容版，见 [docs/SERVICE_PROFILES.md](docs/SERVICE_PROFILES.md)
- **100+ 音色** — 中文 100 个左右 + 英文音色，实际列表以 `kokoro-tts voices` 为准

## 快速开始

> 首次运行时，如果本地没有模型文件，会自动从 HuggingFace 下载。离线部署可参考下方“手动下载模型”。

### pip 安装

```bash
git clone https://github.com/ang77712829/kokoro-tts-zh.git
cd kokoro-tts-zh
pip install -e .

kokoro-tts serve --port 8000
kokoro-tts synth "你好世界" -o hello.wav -v zm_010
kokoro-tts voices
```

### Docker 部署

```bash
# CPU 版本，默认端口 8100
cd docker/cpu && docker compose up -d

# GPU 版本，默认端口 8101，需要 nvidia-container-toolkit
cd docker/gpu && docker compose up -d
```

开发/测试环境想要 `git pull + restart` 生效，可以在 Compose 中取消注释源码挂载：

```yaml
- ../../src:/app/src:ro
```

生产环境建议构建固定镜像：

```bash
docker compose up -d --build
```

### 手动下载模型

```bash
pip install huggingface_hub
huggingface-cli download hexgrad/Kokoro-82M-v1.1-zh \
  --local-dir models/ \
  --include "config.json" "kokoro-v1_1-zh.pth" "voices/*.pt"
```

或使用 Git LFS：

```bash
git lfs install
git clone https://huggingface.co/hexgrad/Kokoro-82M-v1.1-zh /tmp/kokoro-models
cp /tmp/kokoro-models/{config.json,kokoro-v1_1-zh.pth} models/
cp /tmp/kokoro-models/voices/*.pt models/voices/
rm -rf /tmp/kokoro-models
```

## API 接口

### OpenAI 兼容 TTS

```bash
curl -X POST http://localhost:8000/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"model":"kokoro","input":"你好世界","voice":"zm_010","response_format":"wav"}' \
  --output output.wav
```

支持格式：

| 格式 | Content-Type | 说明 |
|---|---|---|
| `wav` | `audio/wav` | 默认格式，兼容性最好 |
| `pcm` | `audio/pcm` | 原始 PCM s16le，适合低开销流式场景 |
| `mp3` | `audio/mpeg` | 需开启 `KOKORO_MP3_ENABLED=true`，并安装 ffmpeg |

查询当前格式支持：

```bash
curl http://localhost:8000/v1/audio/formats
```

### 旧版接口

```bash
curl -X POST http://localhost:8000/api/tts \
  -H "Content-Type: application/json" \
  -d '{"text":"你好世界","voice":"zm_010","format":"wav"}' \
  --output output.wav

curl "http://localhost:8000/api/tts?text=你好世界&voice=zm_010&response_format=wav" --output output.wav
```

### 批量合成 ZIP

```bash
curl -X POST http://localhost:8000/v1/audio/batch \
  -H "Content-Type: application/json" \
  -d '{"voice":"zm_010","speed":1.0,"response_format":"wav","items":[{"text":"第一段","filename":"001"},{"text":"第二段","filename":"002"}]}' \
  --output batch.zip
```

ZIP 内会包含每条音频和 `manifest.json`。

### WebSocket 流式合成

```javascript
const ws = new WebSocket("ws://localhost:8000/ws/v1/tts");

ws.onopen = () => {
  ws.send(JSON.stringify({
    text: "你好世界，这是一段流式合成的语音。",
    voice: "zm_010",
    speed: 1.0,
    format: "pcm_s16le",
    binary: false
  }));
};

ws.onmessage = (e) => {
  if (typeof e.data !== "string") {
    // binary=true 时会收到原始音频帧
    return;
  }
  const msg = JSON.parse(e.data);
  if (msg.type === "audio") {
    playPCM(msg.data);
  }
};

// 主动取消/停止后续段落
ws.send(JSON.stringify({ type: "cancel" }));
// 或 ws.send(JSON.stringify({ type: "stop" }));
```

消息类型：

| 类型 | 说明 |
|---|---|
| `started` | 合成开始 |
| `audio` | 音频数据 |
| `segment_error` | 单段失败 |
| `done` | 合成完成 |
| `cancelled` | 已取消 |
| `error` | 错误 |

### 服务状态

```bash
curl http://localhost:8000/health
curl http://localhost:8000/stats
curl http://localhost:8000/requests
```

### 管理接口

管理接口默认关闭。开启前建议设置 API Key：

```bash
KOKORO_ADMIN_ENABLED=true
KOKORO_API_KEY=change-me
```

接口：

```bash
curl -X DELETE http://localhost:8000/admin/cache \
  -H "Authorization: Bearer change-me"

curl http://localhost:8000/admin/voices \
  -H "Authorization: Bearer change-me"
```

上传 `.pt` 音色还需要：

```bash
KOKORO_VOICE_UPLOAD_ENABLED=true
```

Docker 中需要将 voices 目录挂载为可写：

```yaml
- ../../models/voices:/app/models/voices:rw
```

## 配置

| 变量 | 默认值 | 说明 |
|---|---|---|
| `KOKORO_MODEL_DIR` | `./models` | 模型目录 |
| `KOKORO_HOST` | `0.0.0.0` | 监听地址 |
| `KOKORO_PORT` | `8000` | 端口 |
| `KOKORO_DEVICE` | `auto` | `auto` / `cpu` / `cuda` |
| `KOKORO_WORKERS` | `1` | Uvicorn worker 数，GPU 建议 1 |
| `KOKORO_MAX_CONCURRENT_REQUESTS` | `1` | 单进程最大合成并发 |
| `KOKORO_MAX_TEXT_LENGTH` | `10000` | 单次请求最大文本长度 |
| `KOKORO_SEGMENT_LENGTH` | `100` | 文本切分目标长度 |
| `KOKORO_DEFAULT_VOICE` | `zm_010` | 默认音色 |
| `KOKORO_DEFAULT_SPEED` | `1.0` | 默认语速 |
| `KOKORO_STREAM_FORMAT` | `pcm_s16le` | WebSocket 默认格式 |
| `KOKORO_STREAM_BINARY_ENABLED` | `true` | 是否允许 binary 音频帧 |
| `KOKORO_CACHE_ENABLED` | `true` | 是否启用内存 LRU 缓存 |
| `KOKORO_CACHE_MAX_ITEMS` | `128` | 最大缓存条目数 |
| `KOKORO_QUEUE_STATUS_ENABLED` | `true` | 是否启用 `/requests` |
| `KOKORO_METRICS_ENABLED` | `true` | 是否启用 `/stats` |
| `KOKORO_REQUEST_TIMEOUT_SECONDS` | `300` | 单次合成超时时间 |
| `KOKORO_BATCH_ENABLED` | `true` | 是否启用批量合成 |
| `KOKORO_BATCH_MAX_ITEMS` | `20` | 批量合成最大条数 |
| `KOKORO_ADMIN_ENABLED` | `false` | 是否启用管理接口 |
| `KOKORO_VOICE_UPLOAD_ENABLED` | `false` | 是否允许上传音色 |
| `KOKORO_MP3_ENABLED` | `false` | 是否启用 MP3 输出 |
| `KOKORO_MP3_BITRATE` | `192k` | MP3 比特率 |
| `KOKORO_API_KEY` | - | 设置后启用 Bearer 认证 |
| `KOKORO_CORS_ORIGINS` | `http://localhost:8000` | CORS 允许来源，逗号分隔 |

## 测试

```bash
pip install -e '.[dev]'
pytest
```

服务冒烟测试：

```bash
chmod +x scripts/smoke_test.sh scripts/loop_test.sh
BASE_URL=http://127.0.0.1:8101 ./scripts/smoke_test.sh
N=50 BASE_URL=http://127.0.0.1:8101 ./scripts/loop_test.sh
```

## 项目结构

```text
kokoro-tts-zh/
├── src/kokoro_tts/       # 核心包
│   ├── config.py         # 配置管理
│   ├── engine.py         # TTS 引擎
│   ├── server.py         # FastAPI 服务
│   ├── service_extras.py # 批量/管理/MP3 等扩展接口
│   ├── cli.py            # 命令行工具
│   └── templates/        # Web UI
├── scripts/              # 冒烟/稳定性测试脚本
├── tests/                # 单元测试
├── docker/               # CPU/GPU Docker 配置
├── docs/                 # 部署画像和服务功能说明
├── models/               # 模型文件目录
├── pyproject.toml
├── README.md
└── README_EN.md
```

## 更新日志

### v2.4.0 (2026-05-04)

**新增**
- 新增 `/v1/audio/batch` 批量合成 ZIP，包含 `manifest.json`
- 新增 `/v1/audio/formats` 查询当前支持的输出格式
- 新增管理接口：`/admin/cache`、`/admin/voices`、`/admin/voices/upload`
- 新增可选 MP3 输出，需开启 `KOKORO_MP3_ENABLED=true`
- 新增 WebSocket `cancel` / `stop` 控制帧，用于停止后续段落合成
- Docker CPU/GPU 镜像加入 `ffmpeg`，用于可选 MP3 转码
- Compose 模板补充完整环境变量注释、源码热更新挂载和 voices 可写挂载说明

**改进**
- FastAPI 与包版本同步到 `2.4.0`
- `/health` 返回 batch/admin/mp3 状态
- v2.4 服务功能说明移至 [docs/V2_4_FEATURES.md](docs/V2_4_FEATURES.md)

### v2.3.0 (2026-05-04)

**新增**
- 新增 `/stats`、`/requests`、请求 ID、请求状态追踪和基础统计
- 新增内存 LRU 音频缓存
- WebSocket 支持可选 binary 音频帧
- 新增请求超时控制
- 新增通用服务版和老显卡/保守兼容版部署画像

**改进**
- HTTP 响应增加 `X-Request-ID`
- `/health` 返回缓存状态和并发配置
- 扩展环境变量，支持缓存、metrics、queue status、binary stream 等服务特性

### v2.1.3 (2026-05-04)

**修复**
- 修复 `response_format=mp3` 被错误标记为 `audio/mpeg` 的问题
- 将同步推理放入线程池，并增加进程内并发限制
- 统一校验文本、音色、语速和输出格式
- 文本分段支持无标点长文本硬切
- PCM 编码前进行 `nan_to_num` 和 `clip`
- 段落边界增加轻量淡入淡出和短静音
- Docker 启动脚本不再每次启动重复安装包

### v2.1.2 (2026-05-04)

**新增**
- 模型自动下载
- 离线模型下载文档
- Docker Compose 配置修复
- GPU Docker 更新到 CUDA 12.1.1

### v2.1.1 (2026-05-03)

**新增**
- WebSocket 逐段流式语音合成
- PCM s16le 和 WAV 两种音频格式
- Web UI 流式播放开关和状态指示

### v2.0.1 (2026-05-03)

**安全**
- API Key 时序攻击防护
- CORS 可配置
- 错误信息脱敏
- 文本长度限制

### v1.0 (2026-02-21)

**初始版本**
- 中英文语音合成
- OpenAI 风格 API
- Docker CPU/GPU 部署

## 致谢

- [Kokoro v1.1 模型](https://huggingface.co/hexgrad/Kokoro-82M) — hexgrad
- 原始模型 Apache 2.0 授权
- 本项目 MIT 授权

## License

MIT
