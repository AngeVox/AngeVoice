# Kokoro TTS 中文语音合成

> 基于 [Kokoro v1.1](https://huggingface.co/hexgrad/Kokoro-82M) 的轻量级中文 TTS，支持 HTTP API + WebSocket 流式合成

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

## 特性

- **中英双语** — 中文 pipeline + 英文 G2P 回调，支持中英文混合输入
- **CPU/GPU 自适应** — 自动检测 CUDA，无 GPU 也能跑
- **OpenAI 兼容 API** — 支持 `/v1/audio/speech`，兼容 `model/input/voice/speed/response_format`
- **WebSocket 逐段流式合成** — 按文本段落合成并实时推送 PCM/WAV 分片，支持 JSON/base64 和 binary 音频帧
- **服务化能力** — 内存 LRU 缓存、请求 ID、`/stats`、`/requests`、超时控制、队列状态
- **输入安全校验** — 文本长度、语速、格式统一校验，避免异常请求拖垮服务
- **pip 可安装** — `pip install -e .` 即可使用
- **Docker 一键部署** — 支持 CPU 和 GPU 两种镜像
- **双部署画像** — 通用服务版 + 老显卡/保守兼容版，见 [docs/SERVICE_PROFILES.md](docs/SERVICE_PROFILES.md)
- **100+ 音色** — 中文 100 个（55 女 + 45 男）+ 英文 3 个（2 女 + 1 男）

## 快速开始

> **模型自动下载**：首次运行时，如果本地没有模型文件，会自动从 HuggingFace 下载（约 330MB）。如需离线使用，请参考下方「手动下载模型」。

### pip 安装

```bash
git clone https://github.com/ang77712829/kokoro-tts-zh.git
cd kokoro-tts-zh
pip install -e .

# 启动服务（首次会自动下载模型）
kokoro-tts serve --port 8000

# 命令行合成
kokoro-tts synth "你好世界" -o hello.wav -v zm_010

# 查看可用音色
kokoro-tts voices
```

### Docker 部署

```bash
# CPU 版本（端口 8100，首次自动下载模型）
cd docker/cpu && docker compose up -d

# GPU 通用服务版（端口 8101，需要 nvidia-container-toolkit）
cd docker/gpu && docker compose up -d
```

老显卡、旧驱动、NAS 或保守环境请参考：[服务画像说明](docs/SERVICE_PROFILES.md)。

### 手动下载模型（离线使用）

如果需要离线部署或自动下载太慢，可以手动下载模型文件：

```bash
# 安装 huggingface_hub CLI
pip install huggingface_hub

# 下载模型到 models/ 目录
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

### OpenAI 兼容接口

```bash
curl -X POST http://localhost:8000/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"model":"kokoro","input":"你好世界","voice":"zm_010","response_format":"wav"}' \
  --output output.wav
```

当前 `response_format` 支持：

| 格式 | Content-Type | 说明 |
|------|--------------|------|
| `wav` | `audio/wav` | 默认格式，兼容性最好 |
| `pcm` | `audio/pcm` | 原始 PCM s16le，适合流式/低开销场景 |

> 暂不伪装支持 MP3。如果需要 MP3，请在外层接入 ffmpeg 转码。

### 旧版接口

```bash
# JSON
curl -X POST http://localhost:8000/api/tts \
  -H "Content-Type: application/json" \
  -d '{"text": "你好世界", "voice": "zm_010", "format":"wav"}' \
  --output output.wav

# GET
curl "http://localhost:8000/api/tts?text=你好世界&voice=zm_010&response_format=wav" --output output.wav

# Form
curl -X POST http://localhost:8000/api/tts -F "text=你好世界" --output output.wav
```

### WebSocket 流式接口

通过 WebSocket 实现逐段实时合成播放。服务端会按标点和长度切分文本，每段合成完成后立即推送音频分片：

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
    // binary=true 时，这里会收到原始音频帧
    return;
  }
  const msg = JSON.parse(e.data);
  if (msg.type === "audio") {
    playPCM(msg.data);  // base64 编码的 PCM 音频
  }
};
```

**消息协议：**

| 类型 | 说明 | 字段 |
|------|------|------|
| `started` | 合成开始 | `request_id`, `segments`, `sample_rate`, `channels`, `format`, `dtype` |
| `audio` | 音频数据 | `request_id`, `index`, `data`（base64）, `format`, `sample_rate`, `channels` |
| `segment_error` | 单段失败 | `request_id`, `index`, `message` |
| `done` | 合成完成 | `request_id`, `total_segments` |
| `error` | 错误 | `request_id`, `message` |

### 健康检查 / 服务状态

```bash
curl http://localhost:8000/health
curl http://localhost:8000/stats
curl http://localhost:8000/requests
```

## 可用音色

运行 `kokoro-tts voices` 查看完整音色列表。

| 前缀 | 语言 | 示例 |
|------|------|------|
| `zm_` | 中文 | `zm_010` |
| `zf_` | 中文 | `zf_001` ~ `zf_004` |
| `af_` | 英文 | `af_maple`, `af_sol` |
| `bf_` | 英文 | `bf_vale` |

## 作为库使用

```python
from kokoro_tts import TTSEngine

engine = TTSEngine()
engine.load()

# 合成到内存
wav_bytes = engine.synthesize("你好世界", voice="zm_010", speed=1.0)

# 合成到文件
engine.synthesize_file("你好世界", output_path="output.wav")

# 流式合成（逐段 yield）
for chunk in engine.synthesize_stream("你好世界", voice="zm_010"):
    if chunk["type"] == "audio":
        process_audio(chunk["data"])  # base64 PCM
```

## 配置

环境变量（优先级高于默认值）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `KOKORO_MODEL_DIR` | `./models` | 模型目录 |
| `KOKORO_HOST` | `0.0.0.0` | 监听地址 |
| `KOKORO_PORT` | `8000` | 端口 |
| `KOKORO_DEVICE` | `auto` | 设备 (auto/cpu/cuda) |
| `KOKORO_WORKERS` | `1` | Uvicorn worker 数 |
| `KOKORO_MAX_CONCURRENT_REQUESTS` | `1` | 同一进程内最大合成并发 |
| `KOKORO_MAX_TEXT_LENGTH` | `10000` | 单次请求最大文本长度 |
| `KOKORO_SEGMENT_LENGTH` | `100` | 文本切分目标长度 |
| `KOKORO_DEFAULT_VOICE` | `zm_010` | 默认音色 |
| `KOKORO_DEFAULT_SPEED` | `1.0` | 默认语速 |
| `KOKORO_STREAM_FORMAT` | `pcm_s16le` | WebSocket 默认格式 |
| `KOKORO_STREAM_BINARY_ENABLED` | `true` | 是否允许 WebSocket binary 音频帧 |
| `KOKORO_CACHE_ENABLED` | `true` | 是否启用内存 LRU 音频缓存 |
| `KOKORO_CACHE_MAX_ITEMS` | `128` | 最大缓存条目数 |
| `KOKORO_QUEUE_STATUS_ENABLED` | `true` | 是否启用 `/requests` 状态接口 |
| `KOKORO_METRICS_ENABLED` | `true` | 是否启用 `/stats` 统计接口 |
| `KOKORO_REQUEST_TIMEOUT_SECONDS` | `300` | 单次合成超时时间 |
| `KOKORO_API_KEY` | - | API Key（设置后需认证） |
| `KOKORO_CORS_ORIGINS` | `http://localhost:8000` | CORS 允许来源（逗号分隔） |

## 项目结构

```
kokoro-tts-zh/
├── src/kokoro_tts/       # 核心包
│   ├── __init__.py       # 包入口（懒加载）
│   ├── config.py         # 配置管理
│   ├── engine.py         # TTS 引擎
│   ├── server.py         # FastAPI HTTP + WebSocket 服务
│   ├── cli.py            # 命令行工具
│   └── templates/        # Web UI
├── tests/                # 测试
├── docker/               # Docker 配置
│   ├── cpu/              # CPU 版本
│   └── gpu/              # GPU 通用服务版
├── docs/                 # 服务画像和部署说明
├── models/               # 模型文件（Git LFS）
├── pyproject.toml        # 包配置
├── README.md
└── README_EN.md
```

## 更新日志

### v2.3.0 (2026-05-04)

**新增**
- 服务化版本：新增 `/stats`、`/requests`、请求 ID、请求状态追踪和基础统计
- 新增内存 LRU 音频缓存，重复文本/音色/语速/格式请求可直接命中缓存
- WebSocket 支持可选 binary 音频帧，降低 base64 开销
- 新增请求超时控制，避免长任务无限挂起
- 新增通用服务版和老显卡/保守兼容版两套部署画像说明

**改进**
- HTTP 响应增加 `X-Request-ID`
- `/health` 返回缓存状态和并发配置
- 扩展环境变量，支持开关缓存、metrics、queue status、binary stream 等服务特性

### v2.1.3 (2026-05-04)

**修复**
- 修复 `response_format=mp3` 被错误标记为 `audio/mpeg` 的问题；当前仅声明支持 `wav`/`pcm`
- 将同步推理放入线程池，并增加进程内并发限制，避免阻塞 FastAPI 事件循环
- 统一校验文本、音色、语速和输出格式，改善错误响应
- 文本分段支持无标点长文本硬切，避免超长单段导致失败
- PCM 编码前进行 `nan_to_num` 和 `clip`，避免 int16 溢出爆音
- 段落边界增加轻量淡入淡出和短静音，减少拼接 click/pop
- Docker 启动脚本不再每次启动重复安装包
- 统一版本号为 `2.1.3`

**新增**
- `KOKORO_WORKERS`、`KOKORO_MAX_CONCURRENT_REQUESTS`、`KOKORO_MAX_TEXT_LENGTH`、`KOKORO_SEGMENT_LENGTH` 等环境变量
- WebSocket `started`/`audio` 消息增加 `sample_rate`、`channels` 等元信息

### v2.1.2 (2026-05-04)

**新增**
- 🚀 模型自动下载：本地无模型时自动从 HuggingFace 下载（~330MB）
- 📖 新增「手动下载模型」离线部署文档
- 🔧 修复 Docker Compose 配置（healthcheck、卷挂载、环境变量）
- 🔧 GPU Docker CUDA 11.7.1 → 12.1.1
- 🔧 版本号统一为 2.1.2

### v2.1.1 (2026-05-03)

**新增**
- WebSocket 流式语音合成（`/ws/v1/tts`），支持逐段实时播放
- PCM s16le 和 WAV 两种音频格式
- Web UI 流式播放开关 + WebSocket 状态指示灯
- Docker 集成测试（17 个测试用例）

**改进**
- `engine.py`: 新增 `synthesize_stream()` 生成器方法
- `server.py`: 新增 WebSocket 端点，含 API Key 验证
- `config.py`: 新增 `stream_enabled`、`stream_format` 配置项

### v2.0.1 (2026-05-03)

**安全**
- API Key 时序攻击防护（`hmac.compare_digest`）
- CORS 默认关闭，支持 `KOKORO_CORS_ORIGINS` 配置
- 错误信息脱敏，不再暴露内部异常堆栈
- 文本长度限制（10000 字符），防止 OOM

**修复**
- `engine.py` 缺少 `import os`
- `tts-project-cpu/main.py` 重复函数定义
- 缺失 `static/` 目致 Docker 挂载崩溃
- 无效 fallback 逻辑（相同参数重试）

**清理**
- 删除无用的 `Dockerfile.new`
- Python 版本统一为 `>=3.10`

### v1.1 (2026-05-02)

**新增**
- CORS 中间件支持
- `KOKORO_MODEL_DIR` 环境变量配置
- CPU + GPU 双版本 Docker

**修复**
- `torch.set_num_interop_threads` 重复设置保护

### v1.0 (2026-02-21)

**初始版本**
- 中英文语音合成（Kokoro-82M-v1.1-zh）
- 100+ 音色，语速调节
- OpenAI 风格 API
- Docker CPU/GPU 部署
- 一键启动脚本

## 致谢

- [Kokoro v1.1 模型](https://huggingface.co/hexgrad/Kokoro-82M) — hexgrad
- 原始模型 [Apache 2.0](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/LICENSE) 授权
- 本项目 MIT 授权

## License

MIT
