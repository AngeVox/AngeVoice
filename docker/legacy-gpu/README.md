# legacy-gpu fallback / 老显卡兼容模式画像

`legacy-gpu` is a CUDA 11.8 compatibility fallback. Try the standard `docker/gpu` profile first on NVIDIA hosts. Use this profile only when the standard GPU image cannot start, CUDA/cuDNN is incompatible, or the host driver stack is too old.

`legacy-gpu` 是 CUDA 11.8 兼容模式画像。有 NVIDIA GPU 时建议先试 `docker/gpu`；只有通用 GPU 镜像无法启动、CUDA/cuDNN 不兼容、或宿主机驱动环境较旧时，再切换到本画像。

## Quick start / 快速启动

```bash
cd docker/legacy-gpu
docker compose up -d
```

Default port / 默认端口：

```text
http://localhost:8102
```

Check status / 检查状态：

```bash
curl http://localhost:8102/health
curl http://localhost:8102/v1/models
```

## Default behavior / 默认行为

The default `docker-compose.yml` is conservative:

默认 `docker-compose.yml` 是保守配置：

```env
KOKORO_DEVICE=cuda
ANGEVOICE_ENABLED_MODELS=kokoro,moss,zipvoice
MOSS_EXECUTION_PROVIDER=cpu
MOSS_CUDA_ENABLED=false
MOSS_PROCESS_ISOLATION_ENABLED=true
MOSS_REALTIME_STREAMING_DECODE=true
MOSS_SEGMENT_LENGTH=120
```

Meaning / 含义：

- Kokoro uses GPU.
- MOSS uses CPU by default for stability.
- ZipVoice remains available as a product entry; actual provider is shown in status/diagnostics.
- MOSS CUDA is not exposed by default because older cards may hit `CUBLAS_STATUS_ALLOC_FAILED`, fallback CPU, low GPU utilization, stutter, or artifacts.
- MOSS uses a stability-first segment length (`MOSS_SEGMENT_LENGTH=120`) to reduce mixed-language drift, stutter and artifacts.

- Kokoro 默认使用 GPU。
- MOSS 默认走 CPU，优先稳定。
- ZipVoice 仍以统一产品入口可用；实际 provider 请查看状态/诊断。
- 默认不开放 MOSS CUDA，因为旧卡上可能出现 `CUBLAS_STATUS_ALLOC_FAILED`、fallback CPU、GPU 利用率低、卡顿或失真。
- MOSS 使用稳定优先短分段（`MOSS_SEGMENT_LENGTH=120`），减少中英文混合尾部漂移、卡顿和失真。

## Optional MOSS CUDA / 可选 MOSS CUDA

Advanced users can try the experimental CUDA compose file:

高级用户可尝试实验配置：

```bash
cd docker/legacy-gpu
docker compose -f docker-compose.moss-cuda.yml up -d
```

Use it only for testing. If you see CUDA allocation errors, fallback to CPU, or audio artifacts, return to the default `docker-compose.yml`.

该配置只建议测试使用。如果出现 CUDA 分配失败、fallback CPU、音频异常或卡死，请切回默认 `docker-compose.yml`。

## Profile guidance / 画像选择建议

- `docker/gpu`: recommended NVIDIA profile. Also try this first on Tesla P4/P40/V100 if the host driver is recent.
- `docker/legacy-gpu`: compatibility fallback, not necessarily faster.
- `docker/cpu`: no NVIDIA GPU, NAS, or lowest-risk deployment.

- `docker/gpu`：推荐 NVIDIA 画像。宿主机驱动较新的 Tesla P4/P40/V100 也建议优先尝试。
- `docker/legacy-gpu`：兼容模式，不保证更快。
- `docker/cpu`：无 NVIDIA GPU、NAS、最低风险部署。
