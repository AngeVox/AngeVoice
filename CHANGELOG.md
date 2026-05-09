# Changelog

All notable changes to AngeVoice TTS service will be documented in this file.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [2.6.4.2] - 2026-05-09

### 🛡️ Stability / 稳定性
- **引用计数保护**: EngineManager 增加 `active_count` 引用计数，空闲卸载不会误卸正在使用中的模型
- **引用计数保护**: EngineManager adds `active_count` reference counter; idle unload no longer mistakenly removes in-use models
- **MOSS 超时恢复**: MOSS 推理超时后自动重建 executor 并标记引擎 unhealthy，下次请求自动触发 reload，无需手动重启
- **MOSS 超时恢复**: MOSS inference timeout now auto-rebuilds executor and marks engine unhealthy; next request auto-triggers reload — no manual restart needed
- **健康状态感知**: `/health` 端点新增 `healthy`/`unhealthy_models` 字段，返回 `degraded` 状态码
- **健康状态感知**: `/health` endpoint now exposes `healthy`/`unhealthy_models` fields and returns `degraded` status code

### ⚡ Production / 生产化
- **请求限流**: 新增 per-IP/API-key 令牌桶 QPS 限流，超过限制返回 429
- **请求限流**: Per-IP / per-API-key token-bucket QPS rate limiting; returns 429 on exceed
- **并发队列控制**: 新增最大并发请求队列长度限制，队列满时返回 429
- **并发队列控制**: Max concurrent request queue length limit; returns 429 when queue is full
- **延迟监控**: `/stats` 端点新增 p50/p95/p99 延迟百分位数
- **延迟监控**: `/stats` endpoint now reports p50 / p95 / p99 latency percentiles
- **显存状态**: `/stats` 端点返回 GPU 显存使用率 (CUDA 可用时)
- **显存状态**: `/stats` endpoint reports GPU VRAM usage (when CUDA is available)
- **Docker 健康检查**: 所有 Dockerfile 增加 `HEALTHCHECK` 指令
- **Docker 健康检查**: All Dockerfiles now include a `HEALTHCHECK` directive

### 🔧 Configuration / 配置项
- `KOKORO_RATE_LIMIT_QPS` — 每客户端 QPS 限制 (0 = 禁用) / Per-client QPS limit (0 = disabled)
- `KOKORO_RATE_LIMIT_BURST` — 令牌桶突发容量 / Token-bucket burst capacity
- `KOKORO_MAX_QUEUE_LENGTH` — 最大并发队列长度 (0 = 不限) / Max concurrent queue length (0 = unlimited)

### 🧪 Testing / 测试
- 新增 `e2e_loop_test.sh` 端到端测试脚本，覆盖 health / voices / kokoro / moss / websocket / cancel / idle unload / 循环压测
- Added `e2e_loop_test.sh` end-to-end test script covering health, voices, kokoro, moss, websocket, cancel, idle-unload, and loop stress tests

---

## [2.6.4.1] - 2026-05-08

### 🎯 Features / 新功能
- 空闲超时自动释放显存 (默认关闭) / Idle timeout auto-releases GPU VRAM (disabled by default)
- MOSS 流式解码阈值可配置 / MOSS streaming decode thresholds are now configurable
- 详细 API 文档重写 / Detailed API documentation rewritten

### 🔧 Configuration / 配置项
- `ANGEVOICE_IDLE_TIMEOUT_SECONDS` — 模型空闲超时秒数 (0 = 禁用) / Model idle timeout in seconds (0 = disabled)
- `ANGEVOICE_IDLE_CHECK_INTERVAL` — 空闲检查间隔 / Idle check interval
- `MOSS_STREAM_BUDGET_THRESHOLD_LOW` / `MID` / `HIGH` — 流式解码帧预算 / Streaming decode frame budget thresholds
- `MOSS_STREAM_CHUNK_MIN_FLOOR` — 流式最小分包时长下限 / Streaming minimum chunk duration floor
