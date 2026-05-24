# MOSS 音频质量与长文本自然度调优

本项目只参考 MOSS-TTS-Nano 的官方推理思路，不复制官方 runtime。AngeVoice 在适配层重点解决中文用户常遇到的长文本问题：切片过碎、英文/中英混排硬切、3-5 秒异常静音、流式播放断流感、片段拼接电流感、局部重复读和音色漂移。

## 默认策略

默认值以“稳定、自然、NAS 可承受”为目标：

```env
KOKORO_SEGMENT_LENGTH=160
KOKORO_STREAM_CHUNK_SECONDS=0.55
KOKORO_STREAM_PREBUFFER_SECONDS=0.25

MOSS_SEGMENT_LENGTH=120
MOSS_VOICE_CLONE_MAX_TEXT_TOKENS=56
MOSS_MAX_NEW_FRAMES=320
MOSS_SAMPLE_MODE=fixed
MOSS_SEED=1234
MOSS_APPLY_ANGEVOICE_RULES=auto
MOSS_MIXED_ENGLISH_POLICY=translate
MOSS_STREAM_CHUNK_SECONDS=0.40
MOSS_STREAM_QUEUE_MAX_ITEMS=8
MOSS_STREAM_PREBUFFER_SECONDS=0.75

MOSS_AUDIO_POLISH_ENABLED=true
MOSS_TRIM_SILENCE_ENABLED=true
MOSS_TRIM_SILENCE_DB=-45
MOSS_MAX_SILENCE_MS=480
MOSS_CROSSFADE_MS=12
MOSS_SEGMENT_PAUSE_MS=80
MOSS_RUNTIME_PAUSE_MAX_MS=350
MOSS_OUTPUT_TARGET_PEAK=0.86
MOSS_OUTPUT_GAIN=0.94
MOSS_OUTPUT_EDGE_FADE_MS=1.5
MOSS_VRAM_SNAPSHOT_TTL_SECONDS=10
```

## 这些参数分别解决什么

- `MOSS_MIXED_ENGLISH_POLICY`：MOSS 中英文混排策略。默认 `translate` 会把 deadline、work-life balance、personal growth 等常见英文词组转成自然中文，优先减少长停顿、怪声和尾部漂移；需要保留英文原文时改为 `preserve`。
- `MOSS_SEGMENT_LENGTH`：AngeVoice 外层自然切片长度。默认 120 是 NAS/P4 稳定值，用较短分段降低中英文混合尾部变调、卡顿和失真；高显存机器可在后台切到 180-260。
- `MOSS_VOICE_CLONE_MAX_TEXT_TOKENS`：MOSS runtime 内部切片 token 上限。太小会让一句话被拆成多段，太大则可能增加显存和生成不稳。
- `MOSS_MAX_NEW_FRAMES`：生成帧预算。长句过低可能吞尾、突然断；过高可能拖慢或尾部重复。
- `MOSS_AUDIO_POLISH_ENABLED`：开启最终音频自然化后处理。
- `MOSS_TRIM_SILENCE_ENABLED`：裁掉每个 chunk 首尾异常静音，减少段间“卡住”。
- `MOSS_MAX_SILENCE_MS`：最终音频中超过该上限的连续静音会被压缩。默认 480ms，能减少“卡住几秒”的听感；旁白特别需要长停顿时可提高。
- `MOSS_CROSSFADE_MS`：HTTP 非流式拼接时的短 crossfade，减少硬切电流感。默认 12ms，过大可能抹掉辅音和边界动态。
- `MOSS_SEGMENT_PAUSE_MS`：AngeVoice 外层文本段之间补的短停顿。推荐 80-180。
- `MOSS_RUNTIME_PAUSE_MAX_MS`：MOSS runtime 估算出的内部 chunk pause 上限，避免出现 2-5 秒异常空白。
- `MOSS_STREAM_PREBUFFER_SECONDS`：浏览器开始播放前的初始缓冲。NAS/P4 默认 0.75，用少量首包等待换更少断流；低延迟短句可降到 0.55。

## 推荐预设

### NAS 稳定

```env
MOSS_SEGMENT_LENGTH=120
MOSS_VOICE_CLONE_MAX_TEXT_TOKENS=56
MOSS_MAX_NEW_FRAMES=320
MOSS_STREAM_CHUNK_SECONDS=0.40
MOSS_STREAM_QUEUE_MAX_ITEMS=8
MOSS_MAX_SILENCE_MS=480
MOSS_CROSSFADE_MS=12
MOSS_RUNTIME_PAUSE_MAX_MS=350
```

### 中文长文本旁白（推荐 12GB+ 或确认显存充足后开启）

```env
MOSS_SEGMENT_LENGTH=280
MOSS_VOICE_CLONE_MAX_TEXT_TOKENS=56
MOSS_MAX_NEW_FRAMES=460
MOSS_STREAM_CHUNK_SECONDS=0.40
MOSS_MAX_SILENCE_MS=480
MOSS_CROSSFADE_MS=12
MOSS_SEGMENT_PAUSE_MS=100
MOSS_RUNTIME_PAUSE_MAX_MS=350
```

### 英文/中英混排旁白（推荐 12GB+）

```env
MOSS_SEGMENT_LENGTH=300
MOSS_VOICE_CLONE_MAX_TEXT_TOKENS=96
MOSS_MAX_NEW_FRAMES=480
MOSS_STREAM_CHUNK_SECONDS=0.60
MOSS_MAX_SILENCE_MS=480
MOSS_CROSSFADE_MS=12
MOSS_RUNTIME_PAUSE_MAX_MS=350
```

### 低延迟流式

```env
MOSS_SEGMENT_LENGTH=120
MOSS_STREAM_CHUNK_SECONDS=0.35
MOSS_STREAM_QUEUE_MAX_ITEMS=8
MOSS_STREAM_PREBUFFER_SECONDS=0.55
MOSS_MAX_SILENCE_MS=480
MOSS_CROSSFADE_MS=20
```

## 质量诊断

合成后可以用脚本定位长静音、削波和响度问题：

```bash
python scripts/analyze_audio_quality.py output.wav
```

重点看：

- `clip_ratio`：应接近 0；
- `long_silence_count`：正式旁白最好为 0；
- `max_silence_ms`：默认应被压到 550ms 附近；
- `silence_ratio`：长文本旁白可有自然停顿，但过高会显得卡顿。

## 后台防呆联动（自动收敛）

从 2.6.5.x 起，管理后台在保存配置或应用预设时，会自动收敛几组高风险参数组合，避免“看似可配、实际不稳”：

- `MOSS_VRAM_CRITICAL_FREE_MB` 会自动保持小于 `MOSS_VRAM_SAFE_FREE_MB`；
- 开启实时流式解码时，`MOSS_STREAM_PREBUFFER_SECONDS` 不低于 `MOSS_STREAM_CHUNK_SECONDS`（且最低 0.35）；
- `MOSS_VOICE_CLONE_MAX_TEXT_TOKENS` 不高于 `MOSS_SEGMENT_LENGTH * 0.5`（至少 40）；
- `MOSS_OUTPUT_GAIN` 不高于 `MOSS_OUTPUT_TARGET_PEAK * 1.2`（软上限）。

这样做的目标是：在保证实时对话首包速度的同时，减少爆音、断续、显存尖峰和长句后半段漂移。

## 排查建议

1. 出现 2-5 秒卡顿：先确认 `MOSS_MAX_SILENCE_MS` 和 `MOSS_RUNTIME_PAUSE_MAX_MS` 是否生效。
2. 出现重复读：降低 `MOSS_MAX_NEW_FRAMES` 到 300-400，保持 `MOSS_SAMPLE_MODE=fixed`。
3. 出现尾部吞字：提高 `MOSS_MAX_NEW_FRAMES` 到 460-500，或略降低 `MOSS_SEGMENT_LENGTH`。
4. 流式播放卡顿但保存 WAV 正常：提高 `MOSS_STREAM_PREBUFFER_SECONDS` 到 0.8，或增大 `MOSS_STREAM_CHUNK_SECONDS`。
5. 中文听起来碎：先尝试均衡档 `MOSS_SEGMENT_LENGTH=180-220`；显存充足时再提高到 260，并保持 `MOSS_SEGMENT_PAUSE_MS=80-120`。
