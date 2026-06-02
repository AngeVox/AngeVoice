# Docker 部署画像与持久化

## 支持画像

| profile | 适用场景 | 关键策略 |
| --- | --- | --- |
| `cpu` | 无 GPU NAS、ARM64 CPU NAS | 三模型均使用 CPU 可用路径；ZipVoice 为 ONNX INT8 |
| `gpu` | NVIDIA x86_64，包含 Tesla P4 | Kokoro/MOSS/ZipVoice 请求 CUDA；ZipVoice 不可用时自动回退 CPU |
| `legacy-gpu` | 标准 GPU 镜像无法正常运行的旧驱动/兼容环境 | 使用更保守的 provider 配置 |

用户在界面中选择 `Kokoro v1.1 Chinese`、`MOSS-TTS-Nano` 或 `ZipVoice`；实际 Provider 与回退原因在状态/诊断中展示。

## 启动方式

```bash
# CPU
cd docker/cpu && docker compose up -d

# NVIDIA GPU
cd docker/gpu && docker compose up -d

# Legacy GPU 兼容模式
cd docker/legacy-gpu && docker compose up -d
```

默认 Compose 从 Docker Hub 的 `maxblack777/angevoice-*` 仓库拉取 `latest` 镜像标签，便于持续更新。需要固定部署内容时，可在本地 Compose 或 fnOS 环境变量中将镜像替换为指定标签或 digest。

正式 Docker 画像默认启用 Kokoro、MOSS-TTS-Nano 与 ZipVoice 的可销毁进程隔离，并将启动预载关闭：Studio 仍默认选择 Kokoro，首次生成时自动唤醒模型。管理后台可开启启动预载、关闭单模型隔离，或开启“空闲后彻底清理”。彻底清理默认关闭，只在模型因空闲卸载成功后且服务完全空闲时退出进程，适合需要清理 CUDA/ONNX Runtime 底层残留的 NAS/GPU 环境；关闭隔离后，主机 RAM 不保证在模型释放时完整回落。

## 持久化目录

所有画像使用同一套持久化目录：

```text
models/       模型资产与下载缓存
prompts/      Voice Profiles 与参考音频
outputs/      输出音频
credentials/  管理员哈希凭据与 API Key
config/       后台运行配置
logs/         日志与诊断资料
```

在 CPU、GPU 和 Legacy GPU 模式之间切换时，请继续挂载同一组数据目录。

## NVIDIA 说明

标准 `gpu` 是 NVIDIA 主路径；在宿主机驱动或 CUDA/cuDNN 组合无法兼容标准镜像时，再使用 `legacy-gpu`。ZipVoice 的实际运行方式可在模型状态中查看，CUDA 不可用时可按配置自动回退 CPU ONNX INT8。

fnOS 用户请参阅 [fnOS / FPK 部署](FNOS_FPK.md)。
