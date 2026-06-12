# AngeVoice

> 轻量级中文 TTS 自托管服务。默认使用 Kokoro v1.1 中文模型，可按需切换 MOSS-TTS-Nano 与 ZipVoice；提供 OpenAI 兼容 API、WebSocket 流式、Studio Web UI、浏览器录音、通用音色克隆与管理、批量合成、缓存、统计和 Docker CPU/GPU/老显卡部署。

[English](README_EN.md) | 中文 | [文档目录](docs/README.md)

[![CI](https://github.com/ang77712829/AngeVoice/actions/workflows/ci.yml/badge.svg)](https://github.com/ang77712829/AngeVoice/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-green.svg)](LICENSE)

## 一键安装（推荐普通用户）

服务器已安装 Docker 和 Docker Compose V2 后，可直接运行交互式安装脚本。脚本会自动检测 CPU/GPU、Docker/Compose、GitHub、Docker Hub 与本机 Docker registry mirror。检测到 NVIDIA GPU 时默认推荐通用 `gpu` 画像；`legacy-gpu` 仅用于 `gpu` 无法启动或 CUDA/cuDNN 不兼容的环境。

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/ang77712829/AngeVoice/main/scripts/install.sh)
```

如果你在国内网络访问 GitHub 或 Docker Hub 较慢，可以先下载源码包后执行本地脚本：

```bash
git clone https://github.com/ang77712829/AngeVoice.git
cd AngeVoice
bash scripts/install.sh
```

默认 Docker 配置集中在 `docker/angevoice.env`，CPU/GPU/Legacy 使用统一持久化契约；管理后台默认启用，首次可使用 `admin / admin123` 进入并获取 API Key，公网暴露前必须在安全页修改凭据；`gpu` 是推荐的 NVIDIA 画像，`legacy-gpu` 是兼容画像。

脚本在源码目录内运行时会**就地安装/更新**，不会再额外克隆到 `/opt/angevoice`，更适合 NAS 文件管理。远程 `curl` 方式没有本地项目目录时会自动 bootstrap 完整仓库到 `/opt/angevoice`，所以 `bash <(curl ...install.sh)` 不会因为 `scripts/install/lib/*.sh` 模块缺失而失败。安装完成后会自动读取本机局域网 IP，输出完整访问地址，例如 `http://192.168.1.10:8101`。

生产 Docker 模板默认 `KOKORO_API_KEY=auto`。首次启动会自动生成 API Key 并写入：

```bash
/opt/angevoice/credentials/.angevoice-api-key
# 查看命令
cat /opt/angevoice/credentials/.angevoice-api-key
```

请把这个 token 粘贴到 Studio 设置里的 Bearer Token。新部署可使用默认管理凭据 `admin / admin123` 首次进入后台；进入后会显示安全警告，公网暴露前必须修改为自定义用户名与密码，修改后的凭据只以 PBKDF2 哈希持久化。也可在启动前通过本地 `docker/angevoice.local.env` 覆盖默认凭据。

**管理后台登录凭据：**

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `ANGEVOICE_ADMIN_USERNAME` | `admin` | 管理后台登录用户名 |
| `ANGEVOICE_ADMIN_PASSWORD` | `admin123` | 首次进入的便利密码；公网暴露前必须在后台修改，修改后只保存哈希凭据 |

Docker 部署模板提供 `admin / admin123` 作为首次进入路径，便于普通用户访问控制台与 API Key；后台会显著提示其风险。管理员用户名支持中文，修改后的凭据由独立 `credentials/` 卷保存为 PBKDF2 哈希。生产/公网部署必须先改密，或在启动前通过不提交仓库的本地覆盖文件预设凭据。

安装完成后脚本会创建 `AngeVoice` 管理命令。以后直接输入：

```bash
AngeVoice
```

即可打开菜单，执行安装/更新、重启、停止、卸载、查看状态和访问地址。也可以直接执行：

```bash
bash scripts/install.sh --status
bash scripts/install.sh --restart
bash scripts/install.sh --stop
bash scripts/install.sh --uninstall
```

卸载只停止并移除容器/网络，不删除模型、输出和配置文件。


## 小智 ESP32 后端适配

本仓库新增 `xiaozhi/` 目录，提供小智后端无侵入适配包：

- `xiaozhi/adapters/angevoice.py`：OpenAI 兼容非流式适配，最快跑通。
- `xiaozhi/adapters/angevoice_stream.py`：WebSocket 流式适配，支持 Kokoro/MOSS 流式输出。
- `xiaozhi/adapters/angevoice_clone.py`：MOSS 参考音频克隆非流式适配。
- `xiaozhi/scripts/install-xiaozhi-adapter.sh`：一键安装适配器、patch 小智 Compose、导入智控台数据库预设，并重建 server 容器让挂载生效。
- `xiaozhi/MANAGER_PRESETS.md`：智控台持久化说明，解释 `ai_model_provider` / `ai_model_config`、Docker 权限和容器重建行为。

一键接入小智：

```bash
cd /path/to/xiaozhi-server
bash <(curl -fsSL https://raw.githubusercontent.com/ang77712829/AngeVoice/main/xiaozhi/scripts/install-xiaozhi-adapter.sh)
```

安装脚本是交互式的，普通用户一路按回车会采用推荐默认值。脚本会自动识别 `docker-compose_all.yml` / `docker-compose.yml` / `compose.yml`，支持群晖等 NAS 面板改名后的 compose 文件。

脚本需要 Docker 权限：root 用户可直接运行；普通用户需要加入 `docker` 用户组，或使用 `sudo` / 管理员终端运行。新增 volume 挂载后仅 `docker restart` 不会生效，因此脚本会自动执行：

```bash
docker compose -f <compose文件> up -d --no-deps --force-recreate xiaozhi-esp32-server
```

`--no-deps` 只重建小智 server 容器，不会重建 db/redis，也不会删除 `mysql/data`、`models/`、`uploadfile/` 等持久化数据。

带智控台的小智全模块请优先让脚本导入数据库预设。脚本会写入：

- `ai_model_provider`：让智控台“新增模型”的接口类型出现 `angevoice` / `angevoice_stream` / `angevoice_clone`。
- `ai_model_config`：让“模型配置 → 语音合成”出现 AngeVoice Kokoro、MOSS、ZipVoice 与克隆相关预设。

智控台/API 模式下不要把 `selected_module` / `TTS` 本地配置写进 `data/.config.yaml`，否则小智后端会报“既包含智控台配置又包含本地配置”。脚本检测到 `manager-api:` 时会默认跳过本地配置写入，只保留数据库预设。

MOSS 克隆流式示例：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/ang77712829/AngeVoice/main/xiaozhi/scripts/install-xiaozhi-adapter.sh) \
  --mode moss-clone-stream \
  --prompt-audio ./reference.wav
```

ZipVoice 克隆流式示例：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/ang77712829/AngeVoice/main/xiaozhi/scripts/install-xiaozhi-adapter.sh) \
  --mode zipvoice-stream \
  --prompt-audio ./reference.wav \
  --prompt-text "参考音频实际朗读文本"
```

克隆模式的 `prompt_audio_path` 必须使用小智容器内路径，例如：

```text
/opt/xiaozhi-esp32-server/data/angevoice_prompts/reference.wav
```

ZipVoice 还必须填写 `prompt_text`，并且内容要和参考音频实际朗读文本一致。

不要填写宿主机路径，例如 `/vol*/.../xiaozhi-server/data/angevoice_prompts/`。

完整教程见 [`xiaozhi/README.md`](xiaozhi/README.md)，智控台持久化说明见 [`xiaozhi/MANAGER_PRESETS.md`](xiaozhi/MANAGER_PRESETS.md)。

## 项目定位

AngeVoice 不是重新训练的新模型，而是面向低配设备、NAS 和长期运行环境做的本地 TTS 服务框架。

适合：

- 本地/NAS/家用服务器中文语音合成服务
- Agent、阅读器、有声书、配音工具的 TTS 后端
- OpenAI 兼容 TTS API 后端
- 需要逐段播放、停止生成、批量导出 ZIP 的 Web 应用
- CPU、NVIDIA GPU、老架构 GPU（如 Tesla P4）/ 保守 CUDA 环境

> 核心上游：默认引擎基于 Kokoro v1.1 / Kokoro-82M 中文模型；MOSS-TTS-Nano 集成使用 OpenMOSS 官方运行时；ZipVoice 集成用于零样本音色克隆。三项核心上游均采用 Apache License 2.0，来源与致谢见 `THIRD_PARTY_NOTICES.md` 与 `ACKNOWLEDGEMENTS.md`。

## Studio 预览

![AngeVoice Studio 模型切换](docs/assets/studio-model-switch.png)

![AngeVoice Studio 参考音频克隆](docs/assets/studio-voice-clone.png)

## 核心能力

| 能力 | 说明 |
|---|---|
| Studio Web UI | 内置控制台，支持模型切换、浏览器录制/上传参考音频、Voice Profile 保存/试听/删除、流式播放、停止生成、API Key 设置和统计卡片 |
| API 文档页 | `GET /api-docs` 提供可复制调用示例，重点覆盖 MOSS 参考音频克隆和流式克隆 |
| OpenAI 兼容 API | `POST /v1/audio/speech`，兼容 `model/input/voice/speed/response_format` |
| MOSS-TTS-Nano | 通过 OpenMOSS 官方 ONNX runtime 接入，产品名称与 CPU/CUDA provider 分离；支持预设音色、参考音频克隆与流式体验，实际运行 provider 见诊断状态 |
| 多模型运行时 | `/v1/models` 查看、加载、卸载和切换模型；可切换时卸载旧模型并隔离缓存 |
| TTS 能力查询 | `GET /v1/tts/capabilities` 返回当前模型能力、可用编码格式、音色详情 |
| WebSocket 流式 | `WS /ws/v1/tts` 小包推送；支持 `cancel` / `stop`；MOSS 克隆可在首包传参考音频 base64 |
| 中文文本规则 | 自动断句标点、jieba 分词优先、兜底词典、常见多音字上下文修正 |
| 批量合成 | `POST /v1/audio/batch` 返回 ZIP 和 `manifest.json` |
| 服务治理 | 请求 ID、`/health`、`/stats`、`/requests`、超时、并发限制、LRU 缓存 |
| Docker 画像 | CPU、GPU、老架构 GPU 三套 Compose 画像 |
| CLI | `kokoro-tts serve`（也支持 `python -m kokoro_tts.main serve`） |
| 空闲资源回收 | 默认 10 分钟无人使用后卸载所有已加载模型；可在后台开启“空闲后彻底清理”，让容器在卸载后自动重启一次以释放底层运行时残留 |

## 快速开始

### Docker GPU

```bash
git clone https://github.com/ang77712829/AngeVoice.git
cd AngeVoice/docker/gpu
sudo docker compose up -d
```

默认访问：

```text
http://localhost:8101
```

检查服务：

```bash
curl http://127.0.0.1:8101/health
curl http://127.0.0.1:8101/v1/models
```

> **容器健康状态**：每个 Docker 镜像内置 `HEALTHCHECK`，每 30 秒自动请求 `/health` 端点。返回 `{"status":"ok"}` 或 `{"status":"idle"}` 都判定为 healthy；`idle` 表示模型已被空闲卸载但服务正常可用。`start-period=300s` 确保模型加载期间不会误判。可用 `docker inspect --format='{{json .State.Health}}' <container>` 查看。

### Docker CPU / legacy-gpu 兼容模式

```bash
# CPU，默认端口 8100
cd docker/cpu && sudo docker compose up -d

# legacy-gpu，默认端口 8102
# 仅在 docker/gpu 无法启动或 CUDA/cuDNN 不兼容时使用。
cd docker/legacy-gpu && sudo docker compose up -d
```

> 有 NVIDIA GPU 时建议先试 `docker/gpu`。Tesla P4/P40/V100 等老卡如果宿主机驱动较新，也可能在通用 `gpu` 画像下表现更好；`legacy-gpu` 面向无法使用标准 GPU 镜像的兼容环境。


### 国内镜像加速

Docker Compose 默认使用 Docker Hub（`maxblack777/angevoice-*:latest`）拉取镜像。国内网络访问 Docker Hub 较慢时，可通过 Docker 镜像站加速：

```bash
# 方案 1：临时使用镜像站拉取（替换 registry-1.docker.io 为镜像站地址）
docker pull docker.1ms.run/maxblack777/angevoice-gpu:latest
docker tag docker.1ms.run/maxblack777/angevoice-gpu:latest maxblack777/angevoice-gpu:latest

# 方案 2：配置 Docker daemon 全局镜像加速（推荐）
# 编辑 /etc/docker/daemon.json，添加：
# { "registry-mirrors": ["https://docker.1ms.run"] }
# 然后重启 Docker：sudo systemctl restart docker
```

> 常用镜像站：`docker.1ms.run`、`docker.xuanyuan.me`、`dockerpull.org`。镜像站可用性可能变化，如遇问题请更换其他镜像站。




### `/health` 状态语义

`/health` 返回 HTTP 200 不代表当前模型一定常驻内存，需结合 `status` 字段：

| status | 含义 |
|---|---|
| `ok` | 服务正常，当前模型已加载 |
| `idle` | 服务正常，当前模型因空闲超时已卸载；下次请求会自动加载 |
| `loading` | 服务已启动但当前模型还未完成首次加载 |
| `degraded` | 至少有一个已加载模型 unhealthy |

Docker 健康检查把 `ok` 和 `idle` 都视为 healthy。

## 文档入口

| 入口 | 地址 | 用途 |
|---|---|---|
| Studio | `/` | 图形化合成、试听、模型切换 |
| 管理后台 | `/admin` | 查看状态、切换/释放模型、调整语音质量参数、查看/轮换 API Key |
| API 文档页 | `/api-docs` | 普通用户复制 HTTP/WebSocket/MOSS 克隆示例 |
| Swagger | `/docs` | FastAPI 自动交互式调试文档 |
| ReDoc | `/redoc` | FastAPI 自动阅读型文档 |
| API Reference | [`docs/API_REFERENCE.md`](docs/API_REFERENCE.md) | 仓库内完整接口说明 |
| Troubleshooting | [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) | 常见部署和调用问题 |

## 端口和接口速览

| 部署方式 | HTTP / Web UI | WebSocket |
|---|---|---|
| Docker CPU | `http://localhost:8100` | `ws://localhost:8100/ws/v1/tts` |
| Docker GPU | `http://localhost:8101` | `ws://localhost:8101/ws/v1/tts` |
| Docker 老架构 GPU | `http://localhost:8102` | `ws://localhost:8102/ws/v1/tts` |

| 功能 | 调用 |
|---|---|
| 健康检查 / 统计 / 请求状态 | `GET /health`、`GET /stats`、`GET /requests` |
| 模型列表 / 当前模型 / 切换 | `GET /v1/models`、`GET /v1/models/current`、`POST /v1/models/switch` |
| 音色 / 格式 | `GET /v1/audio/voices`（支持 `?detail=true` 返回性别/显示名）、`GET /v1/audio/formats` |
| TTS 能力查询 | `GET /v1/tts/capabilities` |
| OpenAI 兼容合成 | `POST /v1/audio/speech` |
| 旧版兼容合成 / MOSS 克隆上传 | `GET /api/tts`、`POST /api/tts` |
| WebSocket 流式 / MOSS 克隆流式 | `WS /ws/v1/tts` |
| 批量 ZIP | `POST /v1/audio/batch` |
| 取消请求 | `POST /v1/audio/requests/{request_id}/cancel` |

## 常用 API 示例

### OpenAI 兼容 TTS

```bash
BASE_URL=http://localhost:8000

curl -X POST "$BASE_URL/v1/audio/speech" \
  -H "Content-Type: application/json" \
  -d '{"model":"kokoro","input":"你好世界","voice":"zm_010","response_format":"wav"}' \
  --output output.wav
```

### Base64 JSON 返回（适合 WebView/PWA）

```bash
curl -X POST "$BASE_URL/v1/audio/speech" \
  -H "Content-Type: application/json" \
  -d '{"model":"kokoro","input":"你好世界","voice":"zm_010","response_format":"wav","response_encoding":"base64"}' \
  | jq '.audio_base64' -r | sed 's|data:audio/wav;base64,||' | base64 -d > output.wav
```

> `response_encoding=base64` 返回 JSON，包含 `audio`（裸 base64）、`audio_base64`（data URL）、`sample_rate`、`channels` 等字段。

启用 `KOKORO_API_KEY` 后增加：

```bash
-H "Authorization: Bearer YOUR_TOKEN"
```

### MOSS 参考音频克隆

MOSS 克隆不是把音频放进 `models/models--hexgrad--Kokoro-82M-v1.1-zh/voices`。`models/models--hexgrad--Kokoro-82M-v1.1-zh/voices` 是 Kokoro `.pt` 音色目录。

最推荐的方式是请求时上传参考音频：

```bash
curl -X POST "$BASE_URL/api/tts" \
  -F model=moss \
  -F text="这是参考音频克隆测试。" \
  -F voice=Junhao \
  -F response_format=wav \
  -F prompt_audio=@reference.wav \
  --output clone.wav
```

WebSocket 流式克隆时，参考音频放在首个 JSON 的 `prompt_audio.data`：

```json
{
  "model": "moss",
  "text": "这是参考音频克隆的流式测试。",
  "voice": "Junhao",
  "format": "pcm_s16le",
  "prompt_audio": {
    "filename": "reference.wav",
    "data": "<base64-or-data-url>"
  }
}
```

完整的浏览器 FileReader、Python websockets、Docker 默认参考音频挂载示例见：

- [`/api-docs`](http://localhost:8000/api-docs)
- [`docs/API_REFERENCE.md`](docs/API_REFERENCE.md)

## 模型文件

首次运行时，如果本地没有完整模型文件，服务会按 `ANGEVOICE_MODEL_SOURCE` 自动选择下载源。`auto` 不再只依赖 `ipapi.co`：它会先短超时探测 Hugging Face 与 ModelScope 可达性；若 HF 不可达而 ModelScope 可达会直接走 ModelScope；两者都可达时再用国家/地区判断；国家判断失败时按可达性兜底。也可在管理后台或环境变量中强制设为 `modelscope` / `huggingface`；离线部署可设为 `offline`，此时不会联网下载，需提前准备完整模型。想提升冷启动速度，建议手动准备：

```bash
pipx install huggingface_hub
mkdir -p models/models--hexgrad--Kokoro-82M-v1.1-zh
huggingface-cli download hexgrad/Kokoro-82M-v1.1-zh \
  --local-dir models/models--hexgrad--Kokoro-82M-v1.1-zh \
  --include "config.json" "kokoro-v1_1-zh.pth" "voices/*.pt"
```

推荐的统一模型目录：

```text
models/
├── models--hexgrad--Kokoro-82M-v1.1-zh/
│   ├── config.json
│   ├── kokoro-v1_1-zh.pth
│   └── voices/*.pt
├── MOSS-TTS-Nano-100M-ONNX/
└── modelscope-cache/
```

普通 `git clone` 或 GitHub Source code ZIP 可能只拿到 Git LFS 指针文件，不一定是真实模型文件。如果文件内容以 `version https://git-lfs.github.com/spec/v1` 开头，它只是指针，不是真模型。服务会同时校验 Kokoro 主模型和音色文件，自动跳过 LFS 指针、HTML/JSON 错误页或不完整文件，避免触发 `Weights only load failed` / `Unsupported operand 118`。Kokoro 音色文件本身可以比主模型小很多，因此校验会优先识别文件头，不再因为 131 字节 LFS 指针在长文本合成时反复刷屏。

## Docker 持久化

| 宿主机目录 | 容器目录 | 用途 |
|---|---|---|
| `../../models` | `/app/models` | 统一模型目录；包含 Kokoro、Hugging Face 缓存、ModelScope 缓存和 MOSS ONNX 模型 |
| `../../outputs` | `/app/outputs` | 开启 `ANGEVOICE_SAVE_OUTPUTS=true` 后保存 HTTP 合成结果 |

如需固定服务端默认 MOSS 参考音频，可额外挂载：

```yaml
volumes:
  - ../../prompts:/app/prompts:ro

environment:
  - MOSS_PROMPT_AUDIO_PATH=/app/prompts/reference.wav
```

## 关键配置

| 变量 | 默认值 | 说明 |
|---|---|---|
| `KOKORO_DEVICE` | `auto` | `auto` / `cpu` / `cuda` |
| `KOKORO_WORKERS` | `1` | Uvicorn worker 数；GPU 建议保持 1 |
| `KOKORO_MAX_CONCURRENT_REQUESTS` | `1` | 单进程最大合成并发；NAS/老显卡默认保守，高显存 GPU 可调到 2~4 |
| `KOKORO_API_KEY` | - | 设置后启用 Bearer 鉴权；`auto` 会首次启动生成强随机 key 并写入 `ANGEVOICE_API_KEY_FILE`；占位值会被拒绝 |
| `ANGEVOICE_API_KEY_FILE` | `/app/credentials/.angevoice-api-key` | `KOKORO_API_KEY=auto` 时的持久化 key 文件，管理后台可查看/轮换 |
| `ANGEVOICE_RUNTIME_CONFIG_FILE` | `/app/config/runtime-config.json` | 管理后台保存的运行时配置；优先级高于环境变量，可导出 ENV patch |
| `KOKORO_STREAM_CHUNK_SECONDS` | `0.55` | WebSocket 输出小包时长 |
| `KOKORO_CACHE_ENABLED` | `true` | 是否启用内存 LRU 缓存 |
| `KOKORO_BATCH_ENABLED` | `true` | 是否启用批量合成 |
| `KOKORO_ADMIN_ENABLED` | Docker 默认 `true` | 是否启用管理后台和管理接口；首次可用 `admin / admin123` 登录，公网暴露前必须在后台改密 |
| `ANGEVOICE_FFMPEG_ENABLED` | `false` | 是否启用非流式 HTTP 转码输出，支持 `mp3`、`ogg_opus`/`telegram_voice`、`m4a`；依赖 ffmpeg |
| `ANGEVOICE_FFMPEG_BINARY` | `ffmpeg` | ffmpeg 可执行文件名或路径 |
| `KOKORO_MP3_ENABLED` | `false` | 旧兼容项：设为 true 时视为启用 FFmpeg 转码 |
| `ANGEVOICE_ENABLED_MODELS` | `kokoro,moss,zipvoice` | 启用的公开产品模型 ID；GPU/CPU 实际运行方式由 Provider Policy 与部署画像决定 |
| `ANGEVOICE_DEFAULT_MODEL` | `kokoro` | Studio 启动后默认选中的模型；是否启动加载由 `ANGEVOICE_STARTUP_PRELOAD_ENABLED` 决定 |
| `ANGEVOICE_STARTUP_PRELOAD_ENABLED` | 程序与正式模板默认 `false` | 是否在服务启动后通过 Worker 预载模型；关闭时首次生成会按需唤醒 |
| `ANGEVOICE_STARTUP_PRELOAD_MODEL` | `kokoro` | 开启启动预载时要唤醒的模型 ID |
| `ANGEVOICE_MODEL_UNLOAD_ON_SWITCH` | `true` | 切换模型时卸载旧模型 |
| `ANGEVOICE_SAVE_OUTPUTS` | `true` | 是否保存 HTTP 合成结果，Docker 默认写入 `/app/outputs` |
| `ANGEVOICE_MODELS_ROOT` | `/app/models` | 统一模型根目录，Docker 挂载宿主机 `./models` 到这里 |
| `KOKORO_MODEL_DIR` | `/app/models/models--hexgrad--Kokoro-82M-v1.1-zh` | Kokoro 主模型、config 和 voices 目录 |
| `HF_HUB_CACHE` | `/app/models` | Hugging Face 自动下载缓存根目录，会生成 `models--hexgrad--Kokoro-82M-v1.1-zh` |
| `MODELSCOPE_CACHE` | `/app/models/modelscope-cache` | ModelScope 自动下载缓存目录 |
| `ANGEVOICE_MODEL_SOURCE` | `auto` | 模型下载源：`auto` 先探测 Hugging Face/ModelScope 可达性，再用国家判断；也可手动设为 `modelscope` / `huggingface` / `offline` |
| `KOKORO_MODELSCOPE_REPO` | `AI-ModelScope/Kokoro-82M-v1.1-zh` | 国内自动下载 Kokoro 的 ModelScope 仓库 |
| `MOSS_MODELSCOPE_REPO` | `openmoss/MOSS-TTS-Nano-100M-ONNX` | 自动下载 MOSS ONNX 的 ModelScope 仓库；默认备用源 |
| `MOSS_HF_REPO` | - | 可选 Hugging Face MOSS ONNX 仓库；留空时不走 HF MOSS 下载 |
| `MOSS_MODEL_DIR` | `/app/models/MOSS-TTS-Nano-100M-ONNX` | MOSS ONNX 模型目录 |
| `MOSS_EXECUTION_PROVIDER` | `cpu` | MOSS ONNX provider：`cpu` / `cuda` |
| `MOSS_CUDA_ENABLED` | `false` | 是否允许 `MOSS-TTS-Nano` 请求 CUDA provider；CPU/legacy-gpu 默认关闭，标准 GPU 画像开启 |
| `MOSS_PROMPT_UPLOAD_MAX_BYTES` | `20971520` | MOSS 克隆参考音频上传大小上限 |
| `MOSS_SEGMENT_LENGTH` | `120` | MOSS 专用长文本分段长度，降低中英文混合尾部漂移、卡顿和失真；不影响 Kokoro 的 `KOKORO_SEGMENT_LENGTH` |
| `MOSS_PROMPT_AUDIO_MAX_SECONDS` | `8` | 克隆参考音频裁剪时长 |
| `MOSS_PROMPT_CACHE_MAX_ITEMS` | `8` | 参考音频编码缓存条目数 |
| `MOSS_APPLY_ANGEVOICE_RULES` | `auto` | MOSS 文本规则：中文为主走完整中文规则，中英文/技术文本保守处理，减少版本号、API、英文缩写读坏 |
| `MOSS_MIXED_ENGLISH_POLICY` | `translate` | MOSS 中英文混排策略；默认把常见英文词组转成自然中文，减少长停顿、怪声和尾部漂移 |
| `MOSS_AUTO_FALLBACK_CPU` | `true` | CUDA 自检失败时回退 CPU |
| `MOSS_REALTIME_STREAMING_DECODE` | `true` | 是否启用 MOSS 官方逐帧实时解码；默认开启以保持低延迟流式体验，若特定设备出现边界噪声或显存压力，可在后台关闭 |
| `MOSS_STREAM_PREBUFFER_SECONDS` | `3.0` | MOSS 浏览器流式播放预缓冲，减少老显卡长文本 underflow/断续 |
| `MOSS_STREAM_QUEUE_MAX_ITEMS` | `8` | MOSS 流式队列深度，避免短抖动直接造成播放断流 |
| `KOKORO_PROCESS_ISOLATION_ENABLED` | 程序默认 `false`；Docker/fnOS 模板为 `true` | Kokoro 是否在可销毁 Worker 中运行；正式部署默认开启以便释放 RAM/VRAM |
| `MOSS_PROCESS_ISOLATION_ENABLED` | 程序默认 `false`；Docker/fnOS 模板为 `true` | 是否启用 MOSS 进程级隔离；正式部署模板默认启用，使推理超时后可终止 worker 并自动恢复 |
| `MOSS_PROCESS_ISOLATION_PROVIDERS` | 程序默认 `cuda`；Docker/fnOS 模板为 `cpu,cuda` | 哪些 provider 走隔离子进程，逗号分隔 |
| `MOSS_PROCESS_KILL_GRACE_SECONDS` | `2` | MOSS 超时后终止 worker 的宽限秒数 |
| `ANGEVOICE_WEBSOCKET_STREAM_IDLE_TIMEOUT_SECONDS` | `120` | WebSocket 流式等待下一帧音频的空闲窗口，避免 MOSS 长文本首帧或分段等待时误断开 |
| `ANGEVOICE_ENGINE_PROCESS_STREAM_DRAIN_SECONDS` | `30` | 隔离 Worker 取消后等待旧请求自然排空的窗口 |
| `ANGEVOICE_ENGINE_PROCESS_STREAM_IDLE_TIMEOUT_SECONDS` | `120` | 隔离 Worker 流式请求等待下一帧的空闲窗口，避免慢帧被误判为卡死 |
| `ZIPVOICE_PROCESS_ISOLATION_ENABLED` | 程序默认 `false`；Docker/fnOS 模板为 `true` | ZipVoice 是否在可销毁 Worker 中运行；NAS/GPU 长驻部署建议保持开启 |
| `ANGEVOICE_ENGINE_PROCESS_KILL_GRACE_SECONDS` | `2` | Kokoro/ZipVoice Worker 优雅退出等待秒数，超时后终止以释放资源 |
| `MOSS_QUALITY_GATE_ENABLED` | `true` | 拒绝静音、NaN/Inf 或明显 clipping 的 MOSS 自检输出 |
| `MOSS_OUTPUT_TARGET_PEAK` | `0.86` | MOSS 输出峰值目标，兼顾动态和爆音保护 |
| `MOSS_OUTPUT_GAIN` | `0.94` | MOSS 后处理轻增益，避免默认声音过低并保留动态 |
| `MOSS_OUTPUT_DECLICK_ENABLED` | `true` | 修复孤立瞬态尖峰，降低“噗”“刺”“电流音” |
| `MOSS_OUTPUT_EDGE_FADE_MS` | `1.5` | MOSS 片段头尾短淡入淡出毫秒数，减少拼接爆音且尽量不抹掉辅音 |
| `MOSS_MAX_SILENCE_MS` | `480` | MOSS 最终音频中连续静音压缩上限，减少 1 秒以上卡顿感 |
| `ANGEVOICE_IDLE_TIMEOUT_SECONDS` | `600` | 空闲超时自动卸载所有已加载模型（秒），0=禁用 |
| `ANGEVOICE_IDLE_CHECK_INTERVAL` | `30` | 空闲检查间隔（秒） |
| `ANGEVOICE_RESTART_AFTER_IDLE_UNLOAD` | `false` | 空闲卸载后彻底清理开关；开启后仅在模型因空闲卸载成功且服务完全空闲时退出进程，需 Docker/服务管理器自动拉起 |
| `ANGEVOICE_RESTART_AFTER_IDLE_UNLOAD_DELAY_SECONDS` | `3` | 空闲卸载成功后等待多久再退出；等待期间有新请求会取消本次退出 |
| `ANGEVOICE_RESTART_AFTER_IDLE_UNLOAD_COOLDOWN_SECONDS` | `1800` | 彻底清理触发冷却时间，防止异常环境中频繁重启 |
| `ANGEVOICE_RESTART_AFTER_IDLE_UNLOAD_EXIT_CODE` | `75` | 主动清理退出码，用于日志和运维区分 |
| `MOSS_STREAM_BUDGET_THRESHOLD_LOW` | `0.25` | 音频播放余量低阈值（秒），低于此值每次解码 1 帧以尽快出声 |
| `MOSS_STREAM_BUDGET_THRESHOLD_MID` | `0.65` | 音频播放余量中阈值（秒），低于此值每次解码 2 帧 |
| `MOSS_STREAM_BUDGET_THRESHOLD_HIGH` | `1.20` | 音频播放余量高阈值（秒），低于此值每次解码 4 帧，高于此值每次解码 8 帧 |
| `MOSS_STREAM_CHUNK_MIN_FLOOR` | `0.10` | 流式最小分包时长下限（秒），避免过短碎片造成卡顿感 |
| `MOSS_VRAM_SNAPSHOT_TTL_SECONDS` | `10` | MOSS 显存快照缓存 TTL，减少流式过程中频繁查询 torch/nvidia-smi 造成的卡顿 |
| `KOKORO_RATE_LIMIT_QPS` | `10` | 按 API Key 或客户端 IP 限流；可信内网可设为 0 关闭，运行中修改需重启生效 |
| `KOKORO_RATE_LIMIT_BURST` | `20` | 客户端令牌桶允许的短时突发请求数 |
| `KOKORO_MAX_QUEUE_LENGTH` | `50` | HTTP 同时在途请求入口上限；0=关闭保护 |
| `KOKORO_WS_MAX_CONNECTIONS` | `16` | WebSocket 同时连接上限；0=关闭保护 |
| `KOKORO_WS_MAX_MESSAGE_BYTES` | `33554432` | WebSocket 单条 JSON 消息大小上限，默认兼容 20 MiB 参考音频 base64 首包 |
| `KOKORO_TRUST_PROXY_HEADERS` | `false` | 默认不信任 `X-Forwarded-For`/`X-Real-IP`，避免裸露公网时被伪造绕过限流；确认在可信反代后面才设 true |
| `KOKORO_PUBLIC_STATUS_ENDPOINTS` | `true` | 是否公开 `/v1/models`、`/v1/models/current`、`/v1/audio/voices` 和页面模型目录 bootstrap；公网敏感部署可设为 false，`/health` 仅返回最小健康信息 |

完整配置见 [`docs/API_REFERENCE.md`](docs/API_REFERENCE.md) 和各 Docker Compose 文件。

## 安全说明

- Docker/fnOS 模板默认使用 `KOKORO_API_KEY=auto` 自动生成 API Key，并默认启用基础 HTTP 限流、入口容量和 WebSocket 连接/消息保护；源码直跑若显式留空 API Key，仅适合可信本地网络。
- 管理后台首次可使用 `admin / admin123` 进入，以便获取 API Key；后台会提示默认凭据风险。公网部署必须先修改管理员凭据，修改后磁盘仅保留 PBKDF2 哈希，并应限制 API 来源。
- `.pt` 音色上传默认关闭。只上传可信来源文件；PyTorch 权重文件不应来自不可信渠道。

⚠️ **安全警告**：公网环境**不建议**开启 `KOKORO_VOICE_UPLOAD_ENABLED`。
仅允许上传自己生成或完全可信来源的 `.pt` 文件。
如果必须开放，建议只在内网管理端使用，并配合反代 IP 白名单。
`.pt` 文件是 PyTorch 序列化格式，理论上可执行任意代码。
- 不建议把 `/admin/*` 直接暴露到公网。
- 管理后台仅支持 Basic Auth 登录，普通 Bearer API Key 无法登录管理后台。
- 设置 `KOKORO_PUBLIC_STATUS_ENDPOINTS=false` 后，模型/音色 JSON 接口和页面 bootstrap 会隐藏详细目录；公开 `/health` 只返回最小健康信息。

详见 [`docs/SECURITY.md`](docs/SECURITY.md)。

## 已知限制

- AngeVoice 不是独立训练的新模型，音质、许可证和语言能力受上游模型影响。
- Kokoro、MOSS-TTS-Nano 与 ZipVoice 的 Docker/fnOS 正式模板均默认启用可终止的隔离 Worker；默认启动不预载模型，首次生成会显示唤醒/加载提示。手动关闭隔离后，显存可尝试释放，但主机 RAM 不保证恢复到空闲基线。
- “空闲后彻底清理”默认关闭；只有在空闲卸载成功后才会触发退出，请确认容器使用 `restart: unless-stopped`、`restart: always` 或等效服务管理策略。
- MOSS 的公开产品名称始终为 `MOSS-TTS-Nano`，旧 `moss-nano-cpu` / `moss-nano-cuda` 仅为兼容输入别名。
- 长文本依赖分段合成，极长文本建议走批量/任务队列工作流。
- GPU 场景不建议多 worker 同时加载模型，容易造成显存占用翻倍。
- MP3 输出依赖 ffmpeg。
- WebSocket 是小包音频流，不是 token 级语音生成流。

## 测试

```bash
uv pip install -e '.[dev]'
pytest -q --cov=kokoro_tts --cov-report=term-missing
```

服务端到端测试（需服务已启动）：

```bash
# 完整端到端循环测试：health / voices / 合成 / websocket / cancel / 空闲卸载 / 压测
chmod +x scripts/e2e_loop_test.sh
./scripts/e2e_loop_test.sh http://127.0.0.1:8101              # 无认证，10轮
./scripts/e2e_loop_test.sh http://127.0.0.1:8101 my-key 50    # 带认证，50轮压测
```

轻量冒烟测试：

也可以在 GitHub Actions 手动触发 `Docker CPU Smoke` workflow，验证 `docker compose config --quiet`、CPU 镜像构建、容器启动、`/health` 和 `scripts/smoke_test.sh`。

```bash
chmod +x scripts/smoke_test.sh scripts/loop_test.sh
BASE_URL=http://127.0.0.1:8101 ./scripts/smoke_test.sh
N=50 BASE_URL=http://127.0.0.1:8101 ./scripts/loop_test.sh
```

## 更多文档

- [架构说明](docs/ARCHITECTURE.md)
- [API 参考](docs/API_REFERENCE.md)
- [安全说明](docs/SECURITY.md)
- [排障手册](docs/TROUBLESHOOTING.md)
- [服务画像](docs/SERVICE_PROFILES.md)
- [多模型运行时](docs/MODEL_RUNTIME.md)
- [MOSS 音频听感排障](docs/MOSS_AUDIO_QUALITY.md)
- [老架构 GPU 部署说明](docker/legacy-gpu/README.md)

## 开源许可与致谢

AngeVoice 以 [Apache License 2.0](LICENSE) 开源；项目版权声明见 [NOTICE](NOTICE)。核心模型与运行时集成来自 [Kokoro](https://huggingface.co/hexgrad/Kokoro-82M)、[MOSS-TTS-Nano](https://github.com/OpenMOSS/MOSS-TTS-Nano) 与 [ZipVoice](https://github.com/k2-fsa/ZipVoice)，三项核心上游均按其 Apache License 2.0 条款使用。其他依赖和运行时下载资产仍遵循各自许可证。

详见 [NOTICE](NOTICE)、[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 与 [ACKNOWLEDGEMENTS.md](ACKNOWLEDGEMENTS.md)。
