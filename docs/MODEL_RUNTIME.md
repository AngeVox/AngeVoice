# AngeVoice 模型与运行 Provider

## 稳定产品入口

用户在 Studio 中选择的是产品模型，而不是当前运行实现：

| canonical ID | 用户可见名称 | 定位 |
|---|---|---|
| `kokoro` | Kokoro v1.1 Chinese | 轻量快速、预置音色、实时交互默认推荐 |
| `moss` | MOSS-TTS-Nano | 兼容保留的参考音频克隆后端 |
| `zipvoice` | ZipVoice | 高质量克隆与长文本生成后端 |

Provider 独立展示于 `/health`、`/v1/models`、后台诊断和 Studio 状态区：

```text
requested_provider / actual_provider / fallback / fallback_reason
```

旧 MOSS 输入 alias（如 `moss-nano-cpu`、`moss-nano-cuda`）继续兼容解析为 `moss`；不新增公开 `zipvoice-cpu` 或 `zipvoice-cuda` 模型 ID。

## 部署画像矩阵

| 画像 | Kokoro | MOSS-TTS-Nano | ZipVoice |
|---|---|---|---|
| CPU | CPU | CPU | CPU ONNX INT8 |
| 标准 GPU（Tesla P4 主路径） | CUDA | CUDA 优先 / CPU 回退 | CUDA 优先 / CPU ONNX INT8 回退 |
| Legacy GPU | CUDA | CPU 默认 | CPU ONNX INT8 |

标准 GPU 下的 ZipVoice 可使用 `cuda_pytorch`；实际性能受硬件与驱动环境影响，可通过诊断接口查看 Provider、RTF、显存/RSS 与回退状态。

## 克隆与 Voice Profile

支持参考条件的模型通过通用能力声明与通用服务接入：

```text
VoiceCondition
VoiceProfileService
/v1/voice-profiles/{engine}
/v1/reference-audio/{engine}/preview
```

Studio 的浏览器录音会生成标准 WAV，并与文件上传走同一参考条件链路。保存的 Profile 固化参考 WAV 与对应文本；选择有效 Profile 后，不使用页面残留的临时参考条件。ZipVoice 单人参考音频在界面中提示官方建议少于 3 秒；AngeVoice 允许最多 15 秒且不会自动裁剪，较长录音可能影响速度或质量。网页录音需要 HTTPS 或 localhost 安全来源。

## 流式与实时定位

流式能力只表示分段可以逐步播放，不等价于实时对话。最终文案必须依据实测：首段音频延迟、热 RTF、长文本稳定性、取消释放和多轮资源数据。若门槛不满足，Kokoro 仍为实时交互默认模型，ZipVoice 定位为高质量克隆与长文本。

## 进程隔离、按需唤醒与启动预载

正式 Docker 与 fnOS 模板默认对三个模型开启进程隔离：

```env
KOKORO_PROCESS_ISOLATION_ENABLED=true
MOSS_PROCESS_ISOLATION_ENABLED=true
MOSS_PROCESS_ISOLATION_PROVIDERS=cpu,cuda
ZIPVOICE_PROCESS_ISOLATION_ENABLED=true
ANGEVOICE_STARTUP_PRELOAD_ENABLED=false
ANGEVOICE_STARTUP_PRELOAD_MODEL=kokoro
```

服务启动时默认只在 Studio 中选中 Kokoro，不把模型权重加载进 API 主进程；首次合成会显示正在唤醒/加载模型。用户可在管理后台按模型关闭隔离，或开启启动预载，但关闭隔离后属于线程内运行，主机 RAM 仅尽力释放，不能承诺回到冷启动基线。开启预载时也通过对应 Worker 加载模型，空闲释放或切换模型时结束 Worker，以便操作系统回收 RAM/VRAM。

默认仅保留一个已加载模型运行时：从 Kokoro 切换到 ZipVoice 或 MOSS 时会先释放旧模型 Worker，避免 NAS 内存和 Tesla P4 显存叠加占用。

## 资产、缓存与释放

模型资产通过后台状态/修复能力管理；Voice Profile、模型资产、配置、凭据与输出均为持久化数据。诊断应同时展示 provider、缓存、RSS/GPU 显存、active task、最近 RTF 与资源释放状态。

## Worker 生命周期与诊断字段

隔离运行的模型通过统一状态字段展示实际资源生命周期：

```text
worker_pid / worker_alive / worker_healthy / worker_last_exit_reason
```

`休眠 · Worker 已退出` 表示正常按需释放，不属于故障；模型曾经加载成功后 Worker 非预期退出时，诊断会记录异常原因，并允许下一次请求重新创建干净 Worker。为防止取消或强杀留下的旧消息污染下一次合成，每一代 Worker 均使用新的命令队列和结果队列；同一 Worker 的普通请求与流式请求串行读取结果队列，强制取消仍可直接中止卡住的 Worker。
