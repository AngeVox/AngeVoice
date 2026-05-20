# AngeVoice 2.6.5.1 发布说明

本版本在 2.6.5.0 的基础上继续收敛 MOSS 生产体验，重点面向 NAS、Tesla P4、低功耗家用服务器和中英文混合长文本。

## 重点变化

- 默认 MOSS 体验改为“稳定和自然优先”：更短分段、更高预缓冲、更深流式队列，减少十几秒后卡住、断流、尾部变调和怪声。
- `MOSS_APPLY_ANGEVOICE_RULES=auto`：中文为主文本继续使用完整中文规则；中英文混排、URL、版本号、API 名称、英文缩写等技术文本只做温和处理。
- `MOSS_VRAM_SNAPSHOT_TTL_SECONDS=10`：显存保护不再频繁查询 CUDA/nvidia-smi，减少流式过程的同步卡顿。
- 默认继续关闭 MOSS 进程级隔离，把它保留为 CUDA/ONNX Runtime 卡死排查选项。
- 卸载模型时额外尝试 `torch.cuda.ipc_collect()`；如果 `nvidia-smi` 无运行进程但仍有约 100MiB 占用，通常是驱动 baseline，不代表模型仍占用显存。

## 推荐默认值

```env
MOSS_SEGMENT_LENGTH=120
MOSS_VOICE_CLONE_MAX_TEXT_TOKENS=56
MOSS_STREAM_QUEUE_MAX_ITEMS=8
MOSS_STREAM_PREBUFFER_SECONDS=0.75
MOSS_OUTPUT_TARGET_PEAK=0.86
MOSS_OUTPUT_GAIN=0.94
MOSS_OUTPUT_EDGE_FADE_MS=1.5
MOSS_MAX_SILENCE_MS=480
MOSS_CROSSFADE_MS=12
MOSS_APPLY_ANGEVOICE_RULES=auto
MOSS_VRAM_SNAPSHOT_TTL_SECONDS=10
MOSS_PROCESS_ISOLATION_ENABLED=false
```

## 验证

```bash
bash -n scripts/install.sh
python -m compileall -q src tests scripts
pytest -q
```
