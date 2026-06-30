# fnOS / FPK 部署

AngeVoice 的 fnOS 包采用经过真实安装验证的 **单一 Compose 文件 + 三个互斥 profile service** 机制：`app/docker/docker-compose.yaml` 同时声明 `angevoice-cpu`、`angevoice-gpu` 与 `angevoice-legacy-gpu`，安装向导通过 `COMPOSE_PROFILES=cpu | gpu | legacy-gpu` 在 docker-project 启动前选择且仅选择一个运行路径。

这仍然只有一份 Docker 编排配置文件，不依赖 callback 在容器创建后改写镜像，也不会引入未经验证的单 service 动态镜像/运行时路由。三类镜像默认从 Docker Hub 的 `maxblack777/angevoice-*` 仓库拉取，并固定使用当前版本标签，避免安装时被浮动镜像影响。

## 安装运行模式

| 向导选项 | Profile / service | 镜像 | Provider 策略 |
|---|---|---|---|
| CPU | `cpu` / `angevoice-cpu` | `maxblack777/angevoice-cpu:v2.6.615` | Kokoro、MOSS-TTS-Nano、ZipVoice 均走 CPU |
| NVIDIA GPU | `gpu` / `angevoice-gpu` | `maxblack777/angevoice-gpu:v2.6.615` | NVIDIA 主路径；Kokoro、MOSS、ZipVoice 请求 CUDA，ZipVoice/MOSS 可按策略回退 CPU |
| Legacy GPU | `legacy-gpu` / `angevoice-legacy-gpu` | `maxblack777/angevoice-legacy-gpu:v2.6.615` | 仅标准 GPU 无法可靠运行时回退；Kokoro CUDA，MOSS/ZipVoice 默认 CPU 稳定路径 |

有 NVIDIA GPU 时优先选择 **NVIDIA GPU**；`legacy-gpu` 不是默认推荐路线，仅作为旧驱动或兼容问题的保底。

推荐 4 核 CPU 与 8GB 内存起步。资源较低的设备可以优先使用 Kokoro、降低并发或关闭预载，以获得更稳定的首次下载与长文本合成体验。

## 进程隔离与启动策略

三种 profile 默认均启用：

```env
KOKORO_PROCESS_ISOLATION_ENABLED=true
MOSS_PROCESS_ISOLATION_ENABLED=true
MOSS_PROCESS_ISOLATION_PROVIDERS=cpu,cuda
ZIPVOICE_PROCESS_ISOLATION_ENABLED=true
ANGEVOICE_WEBSOCKET_STREAM_IDLE_TIMEOUT_SECONDS=120
ANGEVOICE_ENGINE_PROCESS_STREAM_IDLE_TIMEOUT_SECONDS=120
ANGEVOICE_RESTART_AFTER_IDLE_UNLOAD=false
ANGEVOICE_STARTUP_PRELOAD_ENABLED=false
ANGEVOICE_STARTUP_PRELOAD_MODEL=kokoro
```

- Studio 启动默认选择 Kokoro，但不立即加载推理模型。
- 首次生成时会提示唤醒/加载模型；生成完成后按空闲策略退出 Worker。
- Worker 退出后，系统可以回收该模型的主机内存与显存。
- 后台可开启“空闲后彻底清理”；默认关闭，开启后只在空闲卸载成功且服务完全空闲时退出进程，由 fnOS/Docker 自动拉起。
- 高级用户可以在管理后台关闭某个模型的进程隔离，页面会提示线程内运行时 RAM 不保证完整回收。
- 用户开启启动预载时，预热仍发生在 Worker 中，不会把模型权重载入 API 主进程。


## FFmpeg 转码开关

FPK 打包源同时在 `app/docker/angevoice.env` 和 `app/docker/docker-compose.yaml` 中声明 FFmpeg 转码相关变量。安装、配置与升级向导提供 `wizard_ffmpeg_enabled` 单选项，启动时会映射为：

```env
ANGEVOICE_FFMPEG_ENABLED=${wizard_ffmpeg_enabled:-false}
ANGEVOICE_FFMPEG_BINARY=ffmpeg
ANGEVOICE_FFMPEG_TIMEOUT_SECONDS=30
ANGEVOICE_AUDIO_MP3_BITRATE=192k
ANGEVOICE_AUDIO_OPUS_BITRATE=32k
ANGEVOICE_AUDIO_AAC_BITRATE=96k
```

默认关闭，避免普通用户在不了解转码依赖时误用。需要 Telegram voice / OGG Opus、MP3 或 M4A 输出时，可以在 fnOS 向导或 AngeVoice 管理后台开启。Compose 镜像固定拉取 `maxblack777/angevoice-*:v2.6.615`。

## 持久化目录

| 目录 | 用途 |
|---|---|
| `${TRIM_PKGVAR}/models` | 模型资产 |
| `${TRIM_PKGVAR}/prompts` | 参考音频与 Voice Profile |
| `${TRIM_PKGVAR}/outputs` | 合成输出 |
| `${TRIM_PKGVAR}/credentials` | 管理员哈希凭据与 API Key |
| `${TRIM_PKGVAR}/config` | 后台运行配置 |
| `${TRIM_PKGVAR}/logs` | 运行日志与诊断资料 |

升级或重新创建容器时，必须保留上述目录。模型不包含在 FPK 内；首次使用某个模型时可能需要下载资产并等待 Worker 加载。

升级脚本只清理旧版曾生成过的临时 profile/compose 路由文件，例如 `${TRIM_PKGVAR}/docker/.env`、`${TRIM_PKGVAR}/app/docker/.env`、`${TRIM_PKGVAR}/cmd/_mode_env.sh`。这些文件不承载用户模型、音色、输出、凭据或后台配置，清理它们可以避免旧版动态路由残留影响新版单 Compose profile 机制。

## 维护约束

- fnOS 使用 `config/resource` 的 `docker-project` 管理容器生命周期。
- callback 只校验向导输入并准备持久化目录，不在 docker-project 已解析后重写 Compose 或镜像。
- CI 必须校验：只有一份 `docker-compose.yaml`；存在三个互斥 profiles；三种镜像均使用当前版本标签；GPU profile 启用 CUDA/GPU 配置；所有 profile 的持久化和 Worker 默认策略一致。
