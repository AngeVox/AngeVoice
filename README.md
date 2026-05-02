# Kokoro TTS 中文语音合成

> 基于 [Kokoro v1.1](https://huggingface.co/hexgrad/Kokoro-82M) 的轻量级中文 TTS

## ✨ 特性

- 🎯 **中英双语** — 自动语言检测，混合文本无缝合成
- 🖥️ **CPU/GPU 自适应** — 自动检测 CUDA，无 GPU 也能跑
- 🔌 **OpenAI 兼容 API** — 直接替代 OpenAI TTS 接口
- 📦 **pip 可安装** — `pip install -e .` 即可使用
- 🐳 **Docker 一键部署** — 支持 CPU 和 GPU 两种镜像
- 🎨 **12+ 音色** — 中文 10 个 + 英文 2 个

## 🚀 快速开始

### 方式一：pip 安装

```bash
# 克隆项目
git clone https://github.com/ang77712829/kokoro-tts-zh.git
cd kokoro-tts-zh

# 安装（需要先安装 Kokoro 依赖）
pip install -e .

# 启动服务
kokoro-tts serve --port 8000

# 命令行合成
kokoro-tts synth "你好世界" -o hello.wav -v zm_010
```

### 方式二：Docker

```bash
# CPU 版本
docker build -f Dockerfile.cpu -t kokoro-tts:cpu .
docker run -d -p 8000:8000 -v $(pwd)/models:/app/models kokoro-tts:cpu

# GPU 版本
docker build -f Dockerfile.gpu -t kokoro-tts:gpu .
docker run -d --gpus all -p 8000:8000 -v $(pwd)/models:/app/models kokoro-tts:gpu
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

### 健康检查

```bash
curl http://localhost:8000/health
```

## 🎨 可用音色

| 音色 ID | 语言 | 风格 |
|---------|------|------|
| `zm_002` | 中文 | 甜美活泼 |
| `zm_003` | 中文 | 沉稳干练 |
| `zm_004` | 中文 | 优雅知性 |
| `zm_005` | 中文 | 温柔少女 |
| `zm_006` | 中文 | 邻家女孩 |
| `zm_007` | 中文 | 气质御姐 |
| `zm_008` | 中文 | 温暖治愈 |
| `zm_009` | 中文 | 阳光少年 |
| `zm_010` | 中文 | 默认女声 |
| `zm_013` | 中文 | 甜美可人 |
| `af_011` | 英文 | - |
| `af_012` | 英文 | - |

## 📁 项目结构

```
kokoro-tts-zh/
├── src/kokoro_tts/       # 核心包
│   ├── __init__.py       # 包入口（懒加载）
│   ├── config.py         # 配置管理（环境变量/默认值）
│   ├── engine.py         # TTS 引擎（CPU/GPU 自适应）
│   ├── server.py         # FastAPI HTTP 服务
│   ├── cli.py            # 命令行工具
│   └── templates/        # Web UI
├── tests/                # 测试
├── tts-project-cpu/      # 旧版 CPU 入口（兼容）
├── tts-project-gpu/      # 旧版 GPU 入口（兼容）
├── run-tts.py            # 旧版直接运行入口（兼容）
├── pyproject.toml        # 包配置
├── Dockerfile.new        # 统一 Dockerfile
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

## 作为库使用

```python
from kokoro_tts import TTSEngine

engine = TTSEngine()
engine.load()

# 合成到内存
wav_bytes = engine.synthesize("你好世界", voice="zm_010", speed=1.0)

# 合成到文件
engine.synthesize_file("你好世界", output_path="output.wav")
```

## 🙏 致谢

- [Kokoro v1.1 模型](https://huggingface.co/hexgrad/Kokoro-82M) — hexgrad
- 原始模型 [Apache 2.0](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/LICENSE) 授权
- 本项目 MIT 授权

## 📄 License

MIT
