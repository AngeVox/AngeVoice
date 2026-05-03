# Kokoro TTS 中文语音合成

> 基于 [Kokoro v1.1](https://huggingface.co/hexgrad/Kokoro-82M) 的轻量级中文 TTS，支持 HTTP API + WebSocket 流式合成

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

## 特性

- **中英双语** — 自动语言检测，混合文本无缝合成
- **CPU/GPU 自适应** — 自动检测 CUDA，无 GPU 也能跑
- **OpenAI 兼容 API** — 直接替代 OpenAI TTS 接口
- **WebSocket 流式合成** — 逐段实时播放，低延迟体验
- **pip 可安装** — `pip install -e .` 即可使用
- **Docker 一键部署** — 支持 CPU 和 GPU 两种镜像
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

# GPU 版本（端口 8101，需要 nvidia-container-toolkit）
cd docker/gpu && docker compose up -d
```

### 手动下载模型（离线使用）

如果需要离线部署或自动下载太慢，可以手动下载模型文件：

```bash
# 安装 huggingface_hub CLI
pip install huggingface_hub

# 下载模型到 models/ 目录
huggingface-cli download hexgrad/Kokoro-82M-v1.1-zh   --local-dir models/   --include "config.json" "kokoro-v1_1-zh.pth" "voices/*.pt"
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
  -d '{"input": "你好世界", "voice": "zm_010"}' \
  --output output.wav
```

### 旧版接口

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
    playPCM(msg.data);  // base64 编码的 PCM 音频
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
│   └── gpu/              # GPU 版本
├── models/               # 模型文件（Git LFS）
├── pyproject.toml        # 包配置
├── README.md
└── README_EN.md
```

## 更新日志

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
