# Kokoro TTS 中文语音合成

> 基于 [Kokoro v1.1](https://huggingface.co/hexgrad/Kokoro-82M) 的轻量级中文 TTS，支持 HTTP API + WebSocket 流式合成

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

## ✨ 特性

- 🎯 **中英双语** — 自动语言检测，混合文本无缝合成
- 🖥️ **CPU/GPU 自适应** — 自动检测 CUDA，无 GPU 也能跑
- 🔌 **OpenAI 兼容 API** — 直接替代 OpenAI TTS 接口
- ⚡ **WebSocket 流式合成** — 逐段实时播放，低延迟体验
- 📦 **pip 可安装** — `pip install -e .` 即可使用
- 🐳 **Docker 一键部署** — 支持 CPU 和 GPU 两种镜像
- 🎨 **12+ 音色** — 中文 10 个 + 英文 2 个

## 🚀 快速开始

### 方式一：pip 安装

```bash
git clone https://github.com/ang77712829/kokoro-tts-zh.git
cd kokoro-tts-zh
pip install -e .

# 启动服务
kokoro-tts serve --port 8000

# 命令行合成
kokoro-tts synth "你好世界" -o hello.wav -v zm_010
```

### 方式二：Docker

```bash
# CPU 版本
cd docker/cpu
docker-compose up -d
# 服务运行在 http://localhost:8100

# GPU 版本
cd docker/gpu
docker-compose up -d
# 服务运行在 http://localhost:8101
```

### 方式三：直接运行

```bash
python run-tts.py           # 启动服务
python run-tts.py voices    # 查看音色
```

## 📡 API 接口

### OpenAI 兼容接口

```bash
curl -X POST http://localhost:8000/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"input": "你好世界", "voice": "zm_010"}' \
  --output output.wav
```

### 旧版接口（兼容）

```bash
# JSON
curl -X POST http://localhost:8000/api/tts \
  -H "Content-Type: application/json" \
  -d '{"text": "你好世界", "voice": "zm_010"}' \
  --output output.wav

# GET
curl "http://localhost:8000/api/tts?text=你好世界&voice=zm_010" --output output.wav

# Form
curl -X POST http://localhost:8000/api/tts -F "text=你好世界" --output output.wav
```

### WebSocket 流式接口

通过 WebSocket 实现逐段实时合成播放：

```javascript
const ws = new WebSocket("ws://localhost:8000/ws/v1/tts");
ws.onopen = () => {
  ws.send(JSON.stringify({
    text: "你好世界，这是一段流式合成的语音。",
    voice: "zm_010",
    speed: 1.0,
    format: "pcm_s16le"  // 或 "wav"
  }));
};
ws.onmessage = (e) => {
  const msg = JSON.parse(e.data);
  if (msg.type === "audio") {
    // msg.data 是 base64 编码的 PCM 音频
    playPCM(msg.data);
  }
};
```

**消息协议：**

| 类型 | 说明 | 字段 |
|------|------|------|
| `started` | 合成开始 | `segments`（段数）, `sample_rate` |
| `audio` | 音频数据 | `index`, `data`（base64）, `format` |
| `done` | 合成完成 | `total_segments` |
| `error` | 错误 | `message` |

### 健康检查

```bash
curl http://localhost:8000/health
```

## 🎨 可用音色

运行 `kokoro-tts voices` 查看完整音色列表。

| 前缀 | 语言 | 示例 |
|------|------|------|
| `zm_` | 中文 | `zm_010` |
| `zf_` | 中文 | `zf_001` ~ `zf_004` |
| `af_` | 英文 | `af_maple`, `af_sol` |
| `bf_` | 英文 | `bf_vale` |

## 📁 项目结构

```
kokoro-tts-zh/
├── src/kokoro_tts/       # 核心包
│   ├── __init__.py       # 包入口（懒加载）
│   ├── config.py         # 配置管理（环境变量/默认值）
│   ├── engine.py         # TTS 引擎（CPU/GPU 自适应）
│   ├── server.py         # FastAPI HTTP + WebSocket 服务
│   ├── cli.py            # 命令行工具
│   └── templates/        # Web UI
├── tests/                # 测试
├── docker/               # Docker 配置
│   ├── cpu/              # CPU 版本
│   └── gpu/              # GPU 版本
├── models/               # 模型文件（Git LFS）
├── tts-project-cpu/      # 旧版 CPU 入口（兼容）
├── tts-project-gpu/      # 旧版 GPU 入口（兼容）
├── pyproject.toml        # 包配置
└── README.md
```

## ⚙️ 配置

环境变量（优先级高于默认值）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `KOKORO_MODEL_DIR` | `./models` | 模型目录 |
| `KOKORO_HOST` | `0.0.0.0` | 监听地址 |
| `KOKORO_PORT` | `8000` | 端口 |
| `KOKORO_DEVICE` | `auto` | 设备 (auto/cpu/cuda) |
| `KOKORO_API_KEY` | - | API Key（设置后需认证） |
| `KOKORO_CORS_ORIGINS` | `http://localhost:8000` | CORS 允许来源（逗号分隔） |

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

## 📋 更新日志

详见 [CHANGELOG.md](CHANGELOG.md)

## 🙏 致谢

- [Kokoro v1.1 模型](https://huggingface.co/hexgrad/Kokoro-82M) — hexgrad
- 原始模型 [Apache 2.0](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/LICENSE) 授权
- 本项目 MIT 授权

## 📄 License

MIT
