# AngeVoice

> 轻量级中文 TTS 自托管服务。AngeVoice 默认基于 Kokoro v1.1 中文模型，支持按需切换 MOSS-TTS-Nano 的本地 TTS 框架，提供 OpenAI 兼容 API、WebSocket 逐段流式、Studio Web UI、中文文本规则、批量合成、缓存、统计和 Docker CPU/GPU/老显卡部署。

[English](README_EN.md) | 中文

[![CI](https://github.com/ang77712829/AngeVoice/actions/workflows/ci.yml/badge.svg)](https://github.com/ang77712829/AngeVoice/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

## 项目定位

AngeVoice 不是重新训练的新模型，而是面向低配设备、NAS 和长期运行环境做的本地 TTS 服务框架。Kokoro v1.1 中文模型是默认引擎；可选模型通过运行时模型管理器接入，第一期适配 MOSS-TTS-Nano ONNX。

适合：

- 本地/NAS/家用服务器中文语音合成服务
- Agent、阅读器、有声书、配音工具的 TTS 后端
- OpenAI 兼容 TTS API 后端
- 需要逐段播放、停止生成、批量导出 ZIP 的 Web 应用
- CPU、NVIDIA GPU、老架构GPU (如Tesla P4) / 保守 CUDA 环境

> 模型来源：默认引擎基于 Kokoro v1.1 / Kokoro-82M 中文模型；可选 MOSS-TTS-Nano 集成使用 OpenMOSS 官方运行时代码。模型版权、许可证与限制请以上游仓库为准。

## 推荐硬件配置

### 最低配置（能运行，体验一般）

- **CPU**：4 核 x86_64（Intel/AMD）
- **内存**：4 GB RAM
- **磁盘**：5 GB 可用空间（代码 + 模型下载约 1.6 GB，加上运行时缓存）
- **网络**：首次部署需联网下载模型（Hugging Face），之后可离线运行
- **备注**：仅 CPU 模式下可基本运行，合成速度较慢，适合轻量使用

### CPU 模式推荐配置

- **CPU**：8 核 x86_64 或更高（Intel i7/Xeon、AMD Ryzen 7/EPYC）
- **内存**：8 GB RAM 及以上
- **磁盘**：5 GB 可用空间，SSD 推荐
- **网络**：首次下载模型需稳定网络
- **备注**：CPU 模式下 8 核以上可获得可接受的响应速度，适合 NAS、家用服务器

### GPU 模式推荐配置

- **GPU**：NVIDIA GPU，显存 ≥ 4 GB（推荐 RTX 3060 / A10 及以上）
- **CUDA**：CUDA 11.8+ / cuDNN 8+
- **CPU**：4 核及以上
- **内存**：8 GB RAM 及以上
- **磁盘**：5 GB 可用空间，SSD 推荐
- **网络**：首次下载模型需稳定网络
- **备注**：GPU 模式合成速度最快，适合高并发或实时场景

### 老架构 GPU 模式推荐配置（如 Tesla P4）

- **GPU**：NVIDIA Tesla P4 / M40 / K80 等老架构卡（显存 ≥ 8 GB）
- **CUDA**：对应老版本 CUDA 驱动（如 CUDA 10.x / 11.x）
- **CPU**：4 核及以上
- **内存**：8 GB RAM 及以上
- **磁盘**：5 GB 可用空间，SSD 推荐
- **网络**：首次下载模型需稳定网络
- **备注**：老架构 GPU 受限于 Compute Capability 和 FP16 支持，需使用专门的 Docker Compose 配置；推荐使用 ONNX 推理模式

### 通用要求

- **操作系统**：Linux（推荐）、macOS、Windows（WSL2）
- **Python**：3.10+
- **模型下载大小**：Kokoro 模型约 **500 MB–1 GB**，MOSS-TTS-Nano 约 **1 GB**；首次启动自动从 Hugging Face 拉取
- **磁盘 I/O**：模型加载和缓存对磁盘读写较敏感，推荐 SSD 或 NVMe

## 功能亮点

| 能力 | 说明 |
|---|---|
| OpenAI 兼容 API | `POST /v1/audio/speech`，兼容 `model/input/voice/speed/response_format` |
| Studio Web UI | 内置前端页面，支持亮/暗主题、音色筛选、收藏、试听、流式播放、停止生成、API Key 设置和可折叠统计卡片 |
| 多模型运行时 | `/v1/models` 查看、加载、卸载和切换模型；切换模型时可卸载旧模型并隔离缓存 |
| MOSS-TTS-Nano | 通过 OpenMOSS 官方 ONNX runtime 接入，支持预设音色、参考音频克隆、CPU 基线和 CUDA 实验模式 |
| 中文文本规则 | 自动断句标点、jieba 分词优先、内置兜底词典、常见多音字上下文修正 |
| WebSocket 流式 | `ws://.../ws/v1/tts` 逐段推送，支持 `cancel` / `stop` 控制帧 |
| 批量合成 | `POST /v1/audio/batch` 返回 ZIP 和 `manifest.json` |
| 服务治理 | 请求 ID、`/health`、`/stats`、`/requests`、超时、并发限制、LRU 缓存 |
| 管理接口 | 可选缓存清理、音色列表、`.pt` 音色上传 |
| 输出格式 | WAV、PCM s16le，可选 MP3，MP3 依赖 ffmpeg |
| Docker | CPU、GPU、老架构GPU (如Tesla P4) 三套 Compose 画像 |
| CLI | 推荐 `angevoice`，旧命令 `kokoro-tts` 继续兼容 |

## v2.6 模块化重构

v2.6 将原来较重的 `server.py` 拆成独立模块，保留原有对外入口：

```text
src/kokoro_tts/
├── server.py             # FastAPI 应用装配：create_app / run_server
├── service_state.py      # 运行时状态、缓存、统计、并发、合成调度
├── security.py           # HTTP / WebSocket API Key 校验
├── api_models.py         # Pydantic 请求模型
├── routes/
│   ├── status.py         # /, /health, /stats, /requests, voices, cancel
│   ├── audio.py          # /v1/audio/speech 与 /api/tts
│   └── ws.py             # /ws/v1/tts
├── service_extras.py     # batch/admin/mp3 扩展接口
├── zh_rules.py           # 中文自动断句、多音字与轻量分词规则
├── audio.py              # WAV / PCM 编码工具
├── engine_manager.py     # 多模型注册、加载、切换和卸载
├── engine.py             # Kokoro 引擎、分段、文本规范化、音频编码
├── moss_engine.py        # MOSS-TTS-Nano 官方 ONNX runtime 适配层
├── config.py             # 配置与环境变量
├── templates/index.html  # Studio Web UI shell
└── static/               # Studio Web UI 样式与脚本
```

兼容性说明：

- Python import 包名仍为 `kokoro_tts`，避免破坏旧代码。
- 发行包名/项目品牌改为 `angevoice`。
- CLI 新增 `angevoice`，旧 `kokoro-tts` 保留为 alias。
- Kokoro 模型加载不依赖发行包名，而依赖上游 `kokoro` 库、模型目录、模型文件名与 Hugging Face repo，因此改项目名不会影响模型加载。

## 快速开始

### Docker GPU

```bash
git clone https://github.com/ang77712829/AngeVoice.git
cd AngeVoice/docker/gpu
sudo docker compose up -d
```

默认访问：`http://localhost:8101`

```bash
curl http://127.0.0.1:8101/health
curl http://127.0.0.1:8101/stats
```

### Docker CPU / 老架构GPU (如Tesla P4)

```bash
# CPU，默认端口 8100
cd docker/cpu && sudo docker compose up -d

# 老架构GPU，默认端口 8102，CUDA 11.8
cd docker/legacy-gpu && sudo docker compose up -d
```

本地构建：

```bash
sudo docker compose up -d --build
```

Docker 镜像现在按画像预装 MOSS 运行时，首次切换到 MOSS 时才下载模型资产：

- CPU 画像默认开放 `kokoro,moss-nano-cpu`，不暴露 CUDA MOSS。
- 通用 GPU 画像默认开放 `kokoro,moss-nano-cpu,moss-nano-cuda`，启动模型仍是 `kokoro`，用户可在 Web UI 里按需切换，MOSS 克隆模式会显示参考音频上传。
- 老架构GPU 画像也预装了 MOSS GPU 依赖，但 Compose 默认只开放 `kokoro,moss-nano-cpu`；确认旧卡/驱动能稳定运行后，再手动加入 `moss-nano-cuda` 并设置 `MOSS_CUDA_ENABLED=true`。

CUDA 模式会先跑 provider/音频质量自检。Tesla P4 已在 Docker 探针中验证可通过 `onnxruntime-gpu==1.20.2` + `nvidia-cudnn-cu12==9.1.0.70` 跑通通用 GPU 画像的 MOSS CUDA 推理；如果目标机器缺 cuDNN 9 或 provider 自检失败，AngeVoice 会回退到 CPU。

### pip 开发安装

```bash
git clone https://github.com/ang77712829/AngeVoice.git
cd AngeVoice
pip install -e .

angevoice serve --port 8000
angevoice synth "你好世界" -o hello.wav -v zm_010
angevoice voices

# 旧命令仍可用
kokoro-tts serve --port 8000
```

## API 示例

### OpenAI 兼容 TTS

```bash
curl -X POST http://localhost:8000/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"model":"kokoro","input":"你好世界","voice":"zm_010","response_format":"wav"}' \
  --output output.wav
```

模型管理：

```bash
curl http://localhost:8000/v1/models

curl -X POST http://localhost:8000/v1/models/switch \
  -H "Content-Type: application/json" \
  -d '{"model":"moss-nano-cpu","unload_previous":true}'
```

MOSS 参考音频克隆使用 `/api/tts` multipart 上传；Studio Web UI 只会在 MOSS 模型可用时显示“参考音频”控件：

```bash
curl -X POST http://localhost:8000/api/tts \
  -F model=moss-nano-cpu \
  -F text="这是参考音频克隆测试。" \
  -F voice=Junhao \
  -F response_format=wav \
  -F prompt_audio=@reference.wav \
  --output clone.wav
```

参考音频仅对支持 `voice_clone` 的模型生效；对 Kokoro 上传参考音频会返回 400。

WebSocket 也支持 MOSS 克隆的逐段流式输出。首个 JSON 消息可携带 `prompt_audio.data`（base64 或 data URL）；Studio Web UI 会在你选择参考音频并开启流式时自动完成这一步：

```json
{
  "model": "moss-nano-cpu",
  "text": "这是参考音频克隆的流式测试。",
  "voice": "Junhao",
  "format": "pcm_s16le",
  "prompt_audio": {
    "filename": "reference.wav",
    "data": "<base64>"
  }
}
```

启用 `KOKORO_API_KEY` 后增加：

```bash
-H "Authorization: Bearer YOUR_TOKEN"
```

支持格式：`wav`、`pcm`、`mp3`。MP3 需开启 `KOKORO_MP3_ENABLED=true` 且环境存在 ffmpeg。

### WebSocket 流式播放

```javascript
const ws = new WebSocket("ws://localhost:8000/ws/v1/tts");

ws.onopen = () => {
  ws.send(JSON.stringify({
    text: "你好世界，这是一段流式合成测试。",
    voice: "zm_010",
    speed: 1.0,
    format: "pcm_s16le",
    binary: false,
    token: "YOUR_TOKEN" // 未启用 KOKORO_API_KEY 时可省略
  }));
};

ws.send(JSON.stringify({ type: "cancel" }));
```

消息类型：`started`、`audio`、`segment_error`、`done`、`cancelled`、`error`。

JSON 音频帧使用 `data` 字段携带 base64 PCM；如果启用 binary 模式，服务会先发送元信息 JSON，再发送二进制音频帧。

### 中文规则示例

AngeVoice 会在进入 Kokoro pipeline 前做轻量中文规则处理：

```text
春花秋月何时了 -> 春花秋月何时瞭。
我想了解一下 -> 我想瞭解一下
银行行长正在听音乐 -> 银杭杭掌正在听音悦
会议12:01开始 -> 会议十二点零一分开始
长中文无标点文本 -> 按词切分后补入停顿标点
```

规则目标是改善常见朗读错误，而不是替代完整中文 NLP。更复杂的人名、地名和专有名词建议在调用侧显式加标点或使用后续 SSML/词典能力。

### 批量合成 ZIP

```bash
curl -X POST http://localhost:8000/v1/audio/batch \
  -H "Content-Type: application/json" \
  -d '{"voice":"zm_010","speed":1.0,"response_format":"wav","items":[{"text":"第一段","filename":"001"},{"text":"第二段","filename":"002"}]}' \
  --output batch.zip
```

## 模型文件

首次运行时，如果本地没有完整模型文件，服务会自动从 Hugging Face 下载。离线部署或想提升冷启动速度，建议手动准备：

```bash
pip install huggingface_hub
huggingface-cli download hexgrad/Kokoro-82M-v1.1-zh \
  --local-dir models/ \
  --include "config.json" "kokoro-v1_1-zh.pth" "voices/*.pt"
```

至少需要：

```text
models/config.json
models/kokoro-v1_1-zh.pth
models/voices/*.pt
```

普通 `git clone` 可能只拿到 Git LFS 指针文件，不一定是真实模型文件。Docker Compose 已持久化 Hugging Face 缓存，避免容器重建后重复下载。

## Docker 持久化

三套 Compose 画像默认准备了这些宿主机挂载：

| 宿主机目录 | 容器目录 | 用途 |
|---|---|---|
| `../../hf_cache` | `/root/.cache/huggingface` | Kokoro/Hugging Face 下载缓存 |
| `../../moss_models` | `/opt/MOSS-TTS-Nano/models` | MOSS ONNX 模型缓存，首次下载后保留 |
| `../../outputs` | `/app/outputs` | 开启 `ANGEVOICE_SAVE_OUTPUTS=true` 后保存 HTTP 合成结果 |

输出文件按日期目录保存，并受 `ANGEVOICE_OUTPUT_MAX_FILES` 控制。MOSS 内部临时文件写入容器临时目录，不会污染持久化输出目录。

## 常用配置

| 变量 | 默认值 | 说明 |
|---|---|---|
| `KOKORO_MODEL_DIR` | `./models` | 模型目录 |
| `KOKORO_HOST` | `0.0.0.0` | 监听地址 |
| `KOKORO_PORT` | `8000` | 服务端口 |
| `KOKORO_DEVICE` | `auto` | `auto` / `cpu` / `cuda` |
| `KOKORO_WORKERS` | `1` | Uvicorn worker 数；GPU 建议保持 1 |
| `KOKORO_MAX_CONCURRENT_REQUESTS` | `1` | 单进程最大合成并发 |
| `KOKORO_REQUEST_TIMEOUT_SECONDS` | `300` | 单次合成超时 |
| `KOKORO_MAX_TEXT_LENGTH` | `10000` | 单次请求最大文本长度 |
| `KOKORO_SEGMENT_LENGTH` | `100` | 文本切分目标长度 |
| `KOKORO_DEFAULT_VOICE` | `zm_010` | 默认音色 |
| `KOKORO_STREAM_BINARY_ENABLED` | `true` | 是否允许 binary 音频帧 |
| `KOKORO_CACHE_ENABLED` | `true` | 是否启用内存 LRU 缓存 |
| `KOKORO_BATCH_ENABLED` | `true` | 是否启用批量合成 |
| `KOKORO_ADMIN_ENABLED` | `false` | 是否启用管理接口 |
| `KOKORO_VOICE_UPLOAD_ENABLED` | `false` | 是否允许上传音色 |
| `KOKORO_MP3_ENABLED` | `false` | 是否启用 MP3 输出 |
| `KOKORO_API_KEY` | - | 设置后启用 Bearer 认证；`change-me` 等占位值会被拒绝 |
| `KOKORO_CORS_ORIGINS` | `http://localhost:8000` | CORS 允许来源，逗号分隔 |
| `ANGEVOICE_ENABLED_MODELS` | `kokoro` | 启用的模型 ID，逗号分隔 |
| `ANGEVOICE_DEFAULT_MODEL` | `kokoro` | 启动时加载的默认模型 |
| `ANGEVOICE_MODEL_UNLOAD_ON_SWITCH` | `true` | Web UI/API 切换模型时卸载旧模型 |
| `ANGEVOICE_SAVE_OUTPUTS` | `false` | 是否保存 HTTP 合成结果 |
| `ANGEVOICE_OUTPUT_DIR` | `/app/outputs` | 生成音频保存目录 |
| `ANGEVOICE_OUTPUT_MAX_FILES` | `1000` | 输出目录最大保留文件数，`0` 表示不自动清理 |
| `MOSS_TTS_NANO_PATH` | - | OpenMOSS/MOSS-TTS-Nano 官方仓库路径 |
| `MOSS_MODEL_DIR` | - | MOSS ONNX 模型目录；Docker 建议 `/opt/MOSS-TTS-Nano/models` |
| `MOSS_EXECUTION_PROVIDER` | `cpu` | MOSS ONNX provider：`cpu` / `cuda` |
| `MOSS_CUDA_ENABLED` | `true` | 是否允许注册/切换 `moss-nano-cuda`；CPU/legacy 默认关闭 |
| `MOSS_CPU_THREADS` | `4` | MOSS CPU ONNX 线程数；NAS 建议 2-4 |
| `MOSS_PROMPT_UPLOAD_MAX_BYTES` | `20971520` | Web UI/API 参考音频上传大小上限 |
| `MOSS_PROMPT_AUDIO_MAX_SECONDS` | `10` | 克隆参考音频裁剪时长，降低显存和延迟 |
| `MOSS_PROMPT_CACHE_MAX_ITEMS` | `8` | 参考音频编码缓存条目数，减少重复 clone 开销 |
| `MOSS_APPLY_ANGEVOICE_RULES` | `true` | MOSS 和后续适配器是否使用 AngeVoice 中文语义、断句、多音字规则 |
| `MOSS_AUTO_FALLBACK_CPU` | `true` | CUDA 自检失败时回退 CPU |
| `MOSS_QUALITY_GATE_ENABLED` | `true` | 拒绝静音、NaN/Inf 或明显 clipping 的 MOSS 自检输出 |
| `MOSS_OUTPUT_PEAK_NORMALIZE_ENABLED` | `true` | 对 MOSS 输出做削峰，降低爆音/削波风险 |
| `MOSS_OUTPUT_TARGET_PEAK` | `0.92` | MOSS 输出削峰目标峰值 |
| `MOSS_OUTPUT_GAIN` | `1.0` | MOSS 输出额外增益；出现爆音时不要调高 |

## 安全说明

- 公网部署建议设置 `KOKORO_API_KEY`，并在反向代理层限制来源。
- 管理接口默认关闭；开启 `KOKORO_ADMIN_ENABLED=true` 时必须设置强 API Key，否则服务会拒绝启动。
- `.pt` 音色上传默认关闭。只上传可信来源文件；PyTorch 权重文件不应来自不可信渠道。
- 不建议把 `/admin/*` 直接暴露到公网。
- `cancel/stop` 会阻止后续段落继续推送；如果当前段已进入同步推理，通常会在当前段结束后停止。

详见 [安全说明](docs/SECURITY.md)。

## 已知限制

- AngeVoice 不是独立训练的新模型，音质、许可证和语言能力受上游模型影响。
- 项目目标是低配设备、NAS 和长期运行环境里的稳定本地 TTS 服务，优先保证实时交互速度、资源可控和可维护性，音质上限取决于上游模型。
- Docker 画像预装匹配的 MOSS 运行时，但默认启动仍是 Kokoro；MOSS 模型资产通过持久化目录按需下载。
- `moss-nano-cuda` 是实验模式；Tesla P4 已验证可跑通，但仍建议在目标机器试听确认无爆音、失真或 clipping 后再长期服务。
- 长文本依赖分段合成，极长文本建议走批量/任务队列工作流。
- GPU 场景下不建议多 worker 同时加载模型，容易造成显存占用翻倍。
- MP3 输出依赖 ffmpeg。
- WebSocket 是逐段流式；MOSS 克隆可通过首包上传参考音频，但仍不是模型内部 token 级真实流式。

## 测试

```bash
pip install -e '.[dev]'
pytest -q --cov=kokoro_tts --cov-report=term-missing
```

服务冒烟测试：

```bash
chmod +x scripts/smoke_test.sh scripts/loop_test.sh
BASE_URL=http://127.0.0.1:8101 ./scripts/smoke_test.sh
N=50 BASE_URL=http://127.0.0.1:8101 ./scripts/loop_test.sh
```

## 文档

- [架构说明](docs/ARCHITECTURE.md)
- [安全说明](docs/SECURITY.md)
- [排障手册](docs/TROUBLESHOOTING.md)
- [服务画像](docs/SERVICE_PROFILES.md)
- [多模型运行时](docs/MODEL_RUNTIME.md)
- [v2.6 功能说明](docs/V2_5_FEATURES.md)
- [路线图](docs/ROADMAP.md)
- [老架构GPU 部署说明](docker/legacy-gpu/README.md)

## License

MIT
