<div align="center">

# AngeVoice

**轻量级中文 TTS 自托管服务**  
基于 **Kokoro v1.1** 模型构建，支持 OpenAI 兼容 API、WebSocket 流式播放、Web UI、批量合成与 Docker 部署。

[![CI](https://github.com/ang77712829/AngeVoice/actions/workflows/ci.yml/badge.svg)](https://github.com/ang77712829/AngeVoice/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Docker](https://img.shields.io/badge/docker-cpu%20%7C%20gpu%20%7C%20legacy--gpu-2496ED.svg)](docker)

**🌐 Language / 语言**

[**English**](README_EN.md) | **中文** (当前)

</div>

---

## 简介

AngeVoice 是由 **安歌** 构建和维护的中文 TTS 服务项目。它不是独立训练的新模型，而是一个围绕 **Kokoro v1.1 中文模型** 做的工程化服务封装，目标是让本地部署、API 调用、Web 流式播放和 Docker 自托管更简单。

适合这些场景：

- 本地/内网中文语音合成服务
- OpenAI 兼容 TTS API 后端
- Agent、阅读器、有声书、配音工具接入
- NAS、家用服务器、GPU/老显卡环境部署
- 需要 WebSocket 逐段播放和停止生成的 Web 应用

> 模型来源：本项目基于 [Kokoro v1.1 / Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) 及其中文模型构建。模型版权、许可证与限制请以原模型仓库为准。

## 功能亮点

| 能力 | 说明 |
|---|---|
| OpenAI 兼容 API | 支持 `/v1/audio/speech`，兼容 `model/input/voice/speed/response_format` |
| Web UI | 内置 AngeVoice 前端页面，支持音色选择、音色试听、流式播放、停止生成 |
| WebSocket 流式 | 支持逐段音频推送、`cancel/stop` 中断、JSON/base64 与可选 binary 音频帧 |
| 批量合成 | `/v1/audio/batch` 返回 ZIP，适合分段配音和有声书流程 |
| 服务化能力 | 请求 ID、`/stats`、`/requests`、超时控制、LRU 缓存、基础统计 |
| 管理接口 | 可选开启缓存清理、音色列表、`.pt` 音色上传 |
| Docker | 提供 CPU、GPU、Legacy GPU 三套 Compose profile |
| 兼容策略 | CLI 保留 `kokoro-tts`，避免破坏旧脚本；服务品牌统一为 AngeVoice |

## 快速开始

### Docker GPU 版

```bash
git clone https://github.com/ang77712829/AngeVoice.git
cd AngeVoice/docker/gpu
sudo docker compose up -d --build
```

访问：

```text
http://localhost:8101
```

检查服务：

```bash
curl http://127.0.0.1:8101/health
curl http://127.0.0.1:8101/stats
```

### Docker CPU / Legacy GPU

```bash
# CPU 版，默认端口 8100
cd docker/cpu
sudo docker compose up -d --build

# Legacy GPU / 老显卡兼容版，默认端口 8102，CUDA 11.8
cd docker/legacy-gpu
sudo docker compose up -d --build
```

### pip 安装

```bash
git clone https://github.com/ang77712829/AngeVoice.git
cd AngeVoice
pip install -e .

kokoro-tts serve --port 8000
kokoro-tts synth "你好世界" -o hello.wav -v zm_010
kokoro-tts voices
```

## API 示例

### OpenAI 兼容 TTS

```bash
curl -X POST http://localhost:8000/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"model":"kokoro","input":"你好世界","voice":"zm_010","response_format":"wav"}' \
  --output output.wav
```

### WebSocket 流式播放

```javascript
const ws = new WebSocket("ws://localhost:8000/ws/v1/tts");

ws.onopen = () => {
  ws.send(JSON.stringify({
    text: "你好世界，这是一段流式合成测试。",
    voice: "zm_010",
    speed: 1.0,
    format: "pcm_s16le",
    binary: false
  }));
};

// 中断后续段落
ws.send(JSON.stringify({ type: "cancel" }));
```

<details>
<summary><strong>更多 API 示例</strong></summary>

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

ZIP 内包含音频文件和 `manifest.json`。

### 状态接口

```bash
curl http://localhost:8000/health
curl http://localhost:8000/stats
curl http://localhost:8000/requests
curl http://localhost:8000/v1/audio/formats
curl http://localhost:8000/v1/audio/voices
```

### 管理接口

管理接口默认关闭，开启前建议设置 API Key：

```bash
KOKORO_ADMIN_ENABLED=true
KOKORO_API_KEY=change-me
```

```bash
curl -X DELETE http://localhost:8000/admin/cache \
  -H "Authorization: Bearer change-me"

curl http://localhost:8000/admin/voices \
  -H "Authorization: Bearer change-me"
```

上传 `.pt` 音色需要额外开启：

```bash
KOKORO_VOICE_UPLOAD_ENABLED=true
```

并将 voices 目录挂载为可写：

```yaml
- ../../models/voices:/app/models/voices:rw
```

</details>

## 模型文件

首次运行时，如果本地没有完整模型文件，服务会自动从 Hugging Face 下载。离线部署或想提升冷启动速度，建议手动准备模型。

<details>
<summary><strong>手动下载模型</strong></summary>

```bash
pip install huggingface_hub
huggingface-cli download hexgrad/Kokoro-82M-v1.1-zh \
  --local-dir models/ \
  --include "config.json" "kokoro-v1_1-zh.pth" "voices/*.pt"
```

或者使用 Git LFS：

```bash
git lfs install
git clone https://huggingface.co/hexgrad/Kokoro-82M-v1.1-zh /tmp/kokoro-models
cp /tmp/kokoro-models/{config.json,kokoro-v1_1-zh.pth} models/
cp /tmp/kokoro-models/voices/*.pt models/voices/
rm -rf /tmp/kokoro-models
```

至少需要：

```text
models/config.json
models/kokoro-v1_1-zh.pth
models/voices/*.pt
```

</details>

## 配置

常用配置已经写入三套 Docker Compose 模板，并配有注释。完整变量如下：

<details>
<summary><strong>环境变量列表</strong></summary>

| 变量 | 默认值 | 说明 |
|---|---|---|
| `KOKORO_MODEL_DIR` | `./models` | 模型目录 |
| `KOKORO_HOST` | `0.0.0.0` | 监听地址 |
| `KOKORO_PORT` | `8000` | 端口 |
| `KOKORO_DEVICE` | `auto` | `auto` / `cpu` / `cuda` |
| `KOKORO_WORKERS` | `1` | Uvicorn worker 数，GPU 建议 1 |
| `KOKORO_MAX_CONCURRENT_REQUESTS` | `1` | 单进程最大合成并发 |
| `KOKORO_REQUEST_TIMEOUT_SECONDS` | `300` | 单次合成超时 |
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
| `KOKORO_BATCH_ENABLED` | `true` | 是否启用批量合成 |
| `KOKORO_BATCH_MAX_ITEMS` | `20` | 批量合成最大条数 |
| `KOKORO_BATCH_CONCURRENCY` | `1` | 批量内部并发，GPU/NAS 建议 1 |
| `KOKORO_ADMIN_ENABLED` | `false` | 是否启用管理接口 |
| `KOKORO_VOICE_UPLOAD_ENABLED` | `false` | 是否允许上传音色 |
| `KOKORO_VOICE_UPLOAD_MAX_BYTES` | `10485760` | 音色上传大小限制 |
| `KOKORO_MP3_ENABLED` | `false` | 是否启用 MP3 输出 |
| `KOKORO_MP3_BITRATE` | `192k` | MP3 比特率，支持 64k/96k/128k/160k/192k/256k/320k |
| `KOKORO_API_KEY` | - | 设置后启用 Bearer 认证 |
| `KOKORO_CORS_ORIGINS` | `http://localhost:8000` | CORS 允许来源，逗号分隔 |

</details>

## 测试与压测

```bash
pip install -e '.[dev]'
pytest -q
```

服务冒烟测试：

```bash
chmod +x scripts/smoke_test.sh scripts/loop_test.sh
BASE_URL=http://127.0.0.1:8101 ./scripts/smoke_test.sh
N=50 BASE_URL=http://127.0.0.1:8101 ./scripts/loop_test.sh
```

流式延迟对比：

```bash
python scripts/benchmark_streaming.py \
  --angevoice-http http://127.0.0.1:8101 \
  --angevoice-ws ws://127.0.0.1:8101/ws/v1/tts
```

## Docker 镜像与发布

GHCR 工作流已准备好。普通 `main` 提交只做构建验证；打 `v*` tag 或手动触发 `publish=true` 时才推送镜像。

预期镜像名：

```text
ghcr.io/ang77712829/angevoice-cpu:v2.4.0
ghcr.io/ang77712829/angevoice-gpu:v2.4.0
ghcr.io/ang77712829/angevoice-legacy-gpu:v2.4.0
```

发布流程见 [docs/RELEASE.md](docs/RELEASE.md)。

## 项目结构

<details>
<summary><strong>查看目录结构</strong></summary>

```text
AngeVoice/
├── src/kokoro_tts/       # 核心包
│   ├── config.py         # 配置管理
│   ├── engine.py         # TTS 引擎与文本规范化
│   ├── server.py         # FastAPI 服务
│   ├── service_extras.py # 批量/管理/MP3 等扩展接口
│   ├── cli.py            # 命令行工具
│   └── templates/        # Web UI
├── scripts/              # 冒烟/稳定性/benchmark 脚本
├── tests/                # 单元测试
├── docker/               # CPU/GPU/Legacy GPU Docker 配置
├── docs/                 # 部署画像、路线图、发布说明
├── models/               # 模型文件目录
├── pyproject.toml
├── README.md
└── README_EN.md
```

</details>

## 文档

- [服务画像](docs/SERVICE_PROFILES.md)
- [v2.4 功能说明](docs/V2_4_FEATURES.md)
- [Legacy GPU 部署说明](docker/legacy-gpu/README.md)
- [路线图](docs/ROADMAP.md)
- [发布指南](docs/RELEASE.md)

## 更新日志

<details>
<summary><strong>v2.4.0</strong></summary>

### 新增

- 新增 AngeVoice Web UI，支持音色试听、流式播放和停止生成
- 新增 `/v1/audio/batch` 批量合成 ZIP，包含 `manifest.json`
- 新增 `/v1/audio/formats` 查询当前支持的输出格式
- 新增管理接口：`/admin/cache`、`/admin/voices`、`/admin/voices/upload`
- 新增可选 MP3 输出，需开启 `KOKORO_MP3_ENABLED=true`
- 新增 WebSocket `cancel` / `stop` 控制帧
- 新增基础中文文本规范化：手机号、日期、金额、百分比、长编号
- 新增 CPU/GPU/Legacy GPU 三套标准化 Docker profile
- 新增 CI、GHCR 构建工作流和 benchmark 脚本

### 改进

- FastAPI、包版本同步到 `2.4.0`
- Docker 服务名统一为 `angevoice-*`
- CLI 保留 `kokoro-tts` 以兼容旧脚本
- `/health` 返回 batch/admin/mp3 状态
- WebSocket cancel 加入背压队列，避免取消后继续推送大量分段
- 上传音色加入大小限制，MP3 bitrate 加入白名单校验
- 测试覆盖更新，CI 已启用 Python 3.10/3.11

</details>

<details>
<summary><strong>历史版本摘要</strong></summary>

### v2.3.0

- 新增 `/stats`、`/requests`、请求 ID、请求状态追踪和基础统计
- 新增内存 LRU 音频缓存
- WebSocket 支持可选 binary 音频帧
- 新增请求超时控制
- 新增通用服务版和老显卡/保守兼容版部署画像

### v2.1.x

- 修复输出格式、并发限制、文本分段、PCM 编码和 Docker 启动问题
- 新增 WebSocket 逐段流式语音合成
- 新增模型自动下载和离线模型下载文档

### v1.0

- 初始中文语音合成、OpenAI 风格 API、Docker CPU/GPU 部署

</details>

## 致谢

- [Kokoro v1.1 模型](https://huggingface.co/hexgrad/Kokoro-82M) — hexgrad
- [Kokoro 中文模型](https://huggingface.co/hexgrad/Kokoro-82M-v1.1-zh) — hexgrad
- 原始模型许可证请以模型仓库为准

## License

MIT
