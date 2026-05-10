# Changelog

All notable changes to AngeVoice TTS service will be documented in this file.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [2.6.4.4] - 2026-05-11

### 🛠️ 修复
- 修复 e2e 脚本在 `set -e` 下使用 `((PASS++))` / `((FAIL++))` 可能提前退出的问题，计数器改为安全自增写法。
- WebSocket e2e 不再只检查 `started`，现在同时验证 `started`、真实 `audio` 分片和 `done` 完成帧。
- idle unload e2e 增加真实“卸载后再请求自动重载”校验；默认超时时长过长时会明确跳过并提示测试环境设置短超时。
- 内置全局 queue limit 不再依赖 `asyncio.Semaphore._value` 私有字段，改为公开状态的非阻塞并发闸门。
- 默认空闲卸载改为 600 秒，并允许释放当前模型；NAS/家用服务器无人使用时可自动释放显存、降低功耗。

### 🎛️ 管理与部署
- 新增 `/admin` 管理后台入口，沿用主站视觉风格；默认关闭，开启后必须配置账号密码。
- 主页右上角新增“管理后台”入口，与 API 文档入口保持一致。
- 三套 Docker 画像统一读取 `docker/angevoice.env`，公共默认值按 CPU/NAS 安全场景设计，GPU 与 legacy-gpu 仅覆盖必要差异。
- 新增 `docker/.env.example` 作为用户本地自定义模板。
- 新增 `scripts/install.sh` 一键安装脚本，可检测 Docker/Compose、NVIDIA GPU、GPU 型号和 GitHub/GHCR 网络情况，并推荐 `cpu` / `gpu` / `legacy-gpu` 画像。

### 🔊 MOSS 体验优化
- MOSS 默认输出策略改为质量优先：更温和的峰值保护、轻微降低输出增益、加大流式最小分片，减少削峰失真、碎片卡顿和块间响度跳变。
- MOSS 流式阈值文档和默认配置对齐，避免 `MOSS_STREAM_BUDGET_THRESHOLD_*` 含义与实际行为不一致。

### 🔧 版本
- 包版本、项目元数据与测试目标版本对齐为 `2.6.4.4`。

---

## [2.6.4.3] - 2026-05-09

### 🛡️ Stability / 稳定性
- **全路径引用计数保护**: `active_count` now protects manual unload, switch-time unload, inactive unload, and idle unload; busy models return 409 or are skipped instead of being released mid-synthesis.
- **全路径引用计数保护**: `active_count` 现在覆盖手动卸载、切换卸载、非活跃卸载和空闲卸载；忙碌模型返回 409 或跳过卸载，避免合成中途释放。
- **MOSS health bridge**: unhealthy MOSS engines are detected through `is_healthy` and reloaded on the next borrow path.
- **MOSS 健康状态桥接**: MOSS unhealthy 状态通过 `is_healthy` 接入 EngineManager，下次 borrow 自动触发重载。
- **Queue gate hardening**: global queue middleware now uses a non-blocking capacity gate without the previous race-prone `locked()` check.
- **队列保护加强**: 全局队列中间件移除旧的 `locked()` 检查，改为非阻塞容量门控。

### 🔧 Release Quality / 发布质量
- **Single version source**: CLI `--version` and FastAPI OpenAPI version now derive from `kokoro_tts.__version__`.
- **统一版本来源**: CLI `--version` 和 FastAPI OpenAPI 版本现在都来自 `kokoro_tts.__version__`。
- **Version bump**: package, project metadata, CLI, OpenAPI, tests, and CI are aligned on `2.6.4.3`.
- **版本对齐**: 包版本、项目元数据、CLI、OpenAPI、测试和 CI 全部对齐为 `2.6.4.3`。

### 🧪 Testing / 测试
- Added unit tests for rate-limit initialization, busy unload 409, switch-with-busy-previous behavior, MOSS health reset, and version consistency.
- 新增限流初始化、忙碌卸载 409、切换时跳过忙碌旧模型、MOSS 健康状态重置、版本一致性等单测。
- Fixed `scripts/e2e_loop_test.sh` to use the real WebSocket endpoint `/ws/v1/tts` and validate binary audio endpoints via HTTP 200 + `audio/*` + output size.
- 修复 `scripts/e2e_loop_test.sh`：WebSocket 使用真实 `/ws/v1/tts`，二进制音频接口用 HTTP 200 + `audio/*` + 文件大小校验。

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
