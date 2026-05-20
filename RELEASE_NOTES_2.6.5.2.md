# AngeVoice 2.6.5.2 发布说明

本版本在 2.6.5.1 的 Kokoro 本地模型校验基础上，针对 MOSS 中英文混排长文本做体验修复。

## 关键变化

- 新增 `MOSS_MIXED_ENGLISH_POLICY=translate`：默认把常见英文词组转成自然中文含义，减少 MOSS 对英文单词的长停顿、怪声和尾部漂移。
- 流式输出也会压缩异常长静音，不只在最终 WAV 拼接时处理。
- `MOSS_MAX_SILENCE_MS` 默认从 550ms 收敛到 480ms，更适合 NAS/Tesla P4 的实时播放体验。
- 技术 token、版本号、IP、API 名称默认仍会保留，避免把 `OpenAI API`、`v2.6.5.2`、`192.168.1.2:8101` 等内容改坏。

## 推荐默认值

```env
MOSS_APPLY_ANGEVOICE_RULES=auto
MOSS_MIXED_ENGLISH_POLICY=translate
MOSS_SEGMENT_LENGTH=120
MOSS_VOICE_CLONE_MAX_TEXT_TOKENS=56
MOSS_STREAM_QUEUE_MAX_ITEMS=8
MOSS_STREAM_PREBUFFER_SECONDS=0.75
MOSS_MAX_SILENCE_MS=480
MOSS_PROCESS_ISOLATION_ENABLED=false
```

需要保留英文原文时，可改为：

```env
MOSS_MIXED_ENGLISH_POLICY=preserve
```
