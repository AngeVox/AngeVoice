# MOSS 推理模块后续拆分计划

本轮 2.6.4.4 优先修复生命周期、e2e、Docker 配置、管理后台和默认体验参数。`src/kokoro_tts/moss_engine.py` 目前仍然偏大，后续建议按“先保持行为一致，再拆模块”的方式逐步重构，避免破坏已经可用的实时流式链路。

## 为什么值得拆分

当前 `moss_engine.py` 同时承担以下职责：

- 官方 OpenMOSS runtime 加载与路径适配
- CPU/CUDA provider 选择、失败回退、自检
- prompt audio 处理、截断、缓存
- 文本清洗、分段、runtime text chunk 管理
- 实时 streaming decode 调度
- 音频后处理、削峰、归一化、分片
- 超时恢复、executor 重建、健康状态

这些职责放在一个文件里会让后续定位“失真、卡顿、CUDA 卡死、缓存失效”等问题变慢，也不利于单测覆盖。

## 建议拆分结构

```text
src/kokoro_tts/moss/
  __init__.py
  engine.py              # 对外 MossNanoEngine，保持现有接口
  runtime_adapter.py     # 官方 runtime 加载、provider、自检、CPU fallback
  prompt_cache.py        # prompt audio 截断、hash、编码缓存
  streaming.py           # streaming decode、帧预算、队列、取消处理
  postprocess.py         # 波形整理、温和峰值保护、分片策略、质量指标
  text.py                # MOSS 专用文本预处理与 chunk 分段
```

## 推荐顺序

1. 先抽 `postprocess.py`：风险最低，能单测削峰/归一化/分片策略，直接服务“减少失真和卡顿”。
2. 再抽 `prompt_cache.py`：减少主引擎复杂度，也方便单测参考音频截断和缓存命中。
3. 再抽 `runtime_adapter.py`：把官方 runtime 加载、CUDA fallback、自检集中管理。
4. 最后抽 `streaming.py`：这是风险最高部分，需要保留 e2e 验证 `started + audio + done` 后再动。

## 本轮已做但未彻底拆分的优化

- Docker 默认 MOSS 参数改为质量优先：温和峰值保护、轻微降低输出增益、增大最小流式分片，减少削峰失真和碎片卡顿。
- e2e 已增强 WebSocket 验证，后续拆 streaming 时可作为安全网。
- MOSS 超时后标记 unhealthy 并重建 executor，但这仍不是彻底进程级隔离；CUDA 硬卡死场景后续应升级为 worker process 隔离。

## 质量调参建议

默认保持稳定：

```env
MOSS_SAMPLE_MODE=fixed
MOSS_SEED=1234
MOSS_OUTPUT_TARGET_PEAK=0.88
MOSS_OUTPUT_GAIN=0.96
MOSS_STREAM_CHUNK_SECONDS=0.42
MOSS_STREAM_CHUNK_MIN_FLOOR=0.10
```

如果用户更想要语气起伏，可以尝试：

```env
MOSS_SAMPLE_MODE=full
MOSS_SEED=-1
MOSS_OUTPUT_TARGET_PEAK=0.90
MOSS_OUTPUT_GAIN=1.0
```

如果用户更想要稳定不爆音，可以保持默认或进一步降低：

```env
MOSS_OUTPUT_TARGET_PEAK=0.85
MOSS_OUTPUT_GAIN=0.94
```
