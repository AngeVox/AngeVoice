## [2.6.614] - 2026-06-29

### 🔧 修复与体验

- 基于 2.6.613 稳定线恢复 Studio Stop 体验：停止本次流式合成不再主动释放或终止模型进程，停止后可立即再次生成。
- 修复 Kokoro 长文本流式取消后仍继续进入下一句合成的问题，降低 Stop 后再次生成的等待时间。
- 首页新增轻量中英切换；文本处理入口改为面向用户的“数字与日期处理”，后台仍可设置默认策略。
- Docker / fnOS 部署模板改用 `v2.6.614` 版本镜像标签；Uvicorn access log 默认关闭，减少 `/health`、`/stats`、`/requests` 探活刷屏。
- fnOS 文案按通用开源部署场景重写，并补充建议至少 4 核 CPU 与 8GB 内存。

## [2.6.613] - 2026-06-11

### 🐛 修复

- 修复 ZipVoice 输入纯数字、小数、百分比、日期、负数与千分位数字时无法稳定合成或读法异常的问题；`3.5`、`-42`、`1,000,000` 等会先转为自然中文读法。
- 补齐带千分位的货币金额读法，`¥1,000`、`1,234.56元` 会读作自然金额，不再残留 `¥` 符号。
- 无可合成文本（URL、代码、日志、JSON、纯符号等）现在返回 `NO_SYNTHESIZABLE_TEXT` 结构化错误，WebSocket 发送 `error` 事件，前端 toast 不再暴露 Python 原始异常。
- 修复非 ASCII API Key 触发 `hmac.compare_digest` TypeError 导致 500 的问题；错误 token 统一按鉴权失败处理。
- 修复 `normalize_text_input(0)` 被 falsy 值吞成空字符串的问题。
- 修复 Kokoro 非流式合成路径误引用 `cancel_check` 导致 HTTP `/v1/audio/speech` / `synthesize_array()` 抛出 `NameError` 的回归。
- 旧版 `/v1/zipvoice/recommended-prompts` 兼容端点补齐 API Key 鉴权；`/v1/admin/cache/clear` 与 `/v1/diagnostics/resources/release` 改为 Admin Auth，避免普通 API Key 清理运行缓存。
- 修复 Kokoro 进程内流式路径未转发 `cancel_check` 的问题；ZipVoice 本地推理不再持有状态锁贯穿整段推理。
- 修复 m4a 转码使用 `pipe:1` 时触发 FFmpeg `ipod` muxer 需要 seekable 输出的问题；m4a 现在使用受控临时文件生成后读取返回。
- 修正上游单层 RNN 无效 dropout 配置，避免 PyTorch 对 `num_layers=1` 且 `dropout>0` 的运行警告；ZipVoice UTMOS 评估模型改用新的 parametrizations `weight_norm` 入口。

### 🔧 格式与文档

- 新增统一 `ANGEVOICE_FFMPEG_ENABLED` 转码开关，非流式 HTTP 支持 `mp3`、`ogg_opus`/`telegram_voice`、`m4a`；WebSocket 流式继续限定 `pcm_s16le` / `wav`。
- 管理后台新增独立“格式转码”配置分组，让 `ANGEVOICE_FFMPEG_ENABLED` 开关、FFmpeg 路径、MP3/Opus/AAC 码率与超时配置在 UI 中明确可见。
- fnOS/FPK 打包源同步 FFmpeg 变量：env、Compose、安装/配置/升级向导与打包校验均包含 `wizard_ffmpeg_enabled` 和转码环境变量。
- `/api-docs` 补齐前端可见的 ZipVoice HTTP 调用导航与示例，覆盖保存音色、multipart 参考音频、`telegram_voice` 输出和流式格式限制。
- 同步版本号、fnOS manifest 与回归测试到 `2.6.613`；Docker / fnOS Compose 镜像仍默认拉取 `maxblack777/angevoice-*:latest`。

## [2.6.612] - 2026-06-08

### 🐛 修复

- 锁定 Docker 镜像中的 `transformers` / `torch` 兼容组合，修复 Kokoro v1.1 在新版 `transformers` 下导入 `AlbertModel` 时访问 `torch.float8_e8m0fnu` 导致的启动失败。
- 固定 MOSS-TTS-Nano 上游源码引用到已验证 commit，避免 Docker 构建时跟随 upstream `main` 漂移。
- Docker 构建阶段新增 Kokoro 与 MOSS runtime import smoke test，提前暴露依赖组合问题。
- 同步版本号、fnOS manifest 与相关回归测试到 `2.6.612`。

## [2.6.611] - 2026-06-04

### 🐛 修复

- 修复正式 Docker 与 fnOS 环境模板中的 `ANGEVOICE_UPDATE_REPOSITORY` 被误改为 Docker Hub 命名空间的问题；版本检查现在重新指向 GitHub 仓库 `ang77712829/AngeVoice`，避免后台“检查更新”返回 404。
- 修复 ZipVoice 隔离 worker 在 CUDA 成功加载时把“支持 CPU 回退”的能力字段误当作“已经回退”的状态字段，导致后台显示 `CUDA · 已回退 CPU` 的问题；现在仅在实际切到 `cpu_onnx_int8` 时展示回退状态和原因。

### 📝 文档与质量

- 保留 Docker Hub 镜像仓库为 `maxblack777/angevoice-*`，并新增发布模板测试，防止更新检查 GitHub 仓库与 Docker Hub 镜像仓库再次混淆。
- 更新版本号、fnOS manifest、CHANGELOG 与相关回归测试到 `2.6.611`。

## [2.6.610] - 2026-06-03

### 🐛 MOSS 稳定性修复

- 修复 MOSS 隔离 worker 将队列结束信号误当作合成完成的问题；流式合成现在必须收到引擎协议 `done` 才算完成，缺失时会明确报错并丢弃截断结果。
- 修复 WebSocket 正常收到 `done` 后仍触发取消信号的问题；完成路径会先等待 producer 释放 worker 锁，只有超出短宽限才进入取消清理。
- 修复 MOSS WebSocket 长文本停止后旧请求占用流式锁，导致下一次合成卡住或重新加载的问题；取消时改为软取消、快速释放连接，并使用请求代次隔离取消信号，避免旧请求的延迟取消误伤新合成。
- 修复 MOSS 长文本首帧或分段之间短暂无音频时被普通请求超时误判断开的问题；新增 WebSocket 与隔离 Worker 的流式空闲等待窗口，并发送轻量进度帧保活。
- 保留 request_id 过滤，避免停止后旧请求残留帧污染下一次合成；MOSS 子进程不再把共享取消标志注入模型内部，只在输出帧之间截断，避免长文本流被误判取消。
- 修复流式生产者提前结束但缺少 `done` 终止帧时前端只停留在“已接收音频块”并静默断开的情况；现在会明确报错，不再把截断结果伪装成合成完成。
- 将 MOSS 默认浏览器预缓冲提升到 `3.0s`，并允许后台/环境变量调到 `12s`，减少长文本分段间隔造成的播放中途断续；逐帧流式默认保持开启，延续主线低延迟体验。

### ♻️ 空闲资源回收

- 新增“空闲卸载后彻底清理”可选功能：模型因空闲自动卸载后，若服务没有活跃请求、WebSocket 连接或已加载模型，可按配置退出进程，由 Docker/服务管理器自动拉起，帮助释放 CUDA/ONNX Runtime 底层残留资源。
- 手动释放模型和空闲自动卸载现在共用安全重启排程；只有无活跃请求、无 WebSocket、无已加载模型时才安排退出，`/health` 与资源诊断会返回 `restarting` 状态。
- 新增后台配置项与 ENV：`ANGEVOICE_RESTART_AFTER_IDLE_UNLOAD`、`ANGEVOICE_RESTART_AFTER_IDLE_UNLOAD_DELAY_SECONDS`、`ANGEVOICE_RESTART_AFTER_IDLE_UNLOAD_COOLDOWN_SECONDS`、`ANGEVOICE_RESTART_AFTER_IDLE_UNLOAD_EXIT_CODE`。默认关闭，不影响常规体验。

### 🔧 配置与接口硬化

- 状态接口统一使用实际生效 API Key 判断鉴权状态，修复持久化 key 场景下前端误判无需鉴权的问题。
- OpenAI 兼容 `/v1/audio/speech` 在 JSON 解析前执行请求体大小限制，避免超大请求提前占用内存。
- `/health` 在懒加载可唤醒状态下返回 `idle`，不再把未预加载但可用的服务误报为 `loading`。
- 新增 `ANGEVOICE_WEBSOCKET_STREAM_IDLE_TIMEOUT_SECONDS`、`ANGEVOICE_ENGINE_PROCESS_STREAM_DRAIN_SECONDS`、`ANGEVOICE_ENGINE_PROCESS_STREAM_IDLE_TIMEOUT_SECONDS`，用于长文本流式等待和取消排空。
- Docker Compose 与 fnOS 默认镜像切换为 Docker Hub `maxblack777/angevoice-*:latest`，GitHub Actions 仍同步发布 GHCR 作为备用仓库。
- MOSS 未加载或刚切换时也会公开完整预设音色目录，避免 Web 端只显示 `Junhao`。
- 小智新安装脚本、示例和智控台预设统一使用公开模型 ID `moss`，并补齐 ZipVoice 克隆流式/非流式预设；旧 `moss-nano-cpu` / `moss-nano-cuda` 仍作为兼容输入保留。
- fnOS 升级流程会清理旧版临时 profile/compose 路由文件，同时保留模型、音色、输出、凭据和后台运行配置目录。

### 📝 文档与质量

- 版本号更新到 `2.6.610`，同步中英文 README、API/架构/部署/运行时/排障文档、Docker/fnOS 环境模板与 manifest。
- 拆分部分高复杂度配置与路由辅助逻辑，新增 MOSS 停止循环、长文本流式等待、空闲彻底清理的回归测试。

## [2.6.602] - 2026-05-26

### 🐛 Worker 生命周期修复

- **cancel 后 stale frame 无限重置 deadline**：取消流式请求后，残留帧会反复重置超时计时器，导致后续请求响应延迟甚至挂起。新增 `cancel_flag` 共享内存软取消机制 + 5 秒 drain 宽限期，超时自动强制终止 worker。
- **CUDA 上下文销毁时间不足**：kill 模式下 grace 时间从 2 秒提升到至少 5 秒，给 CUDA context 销毁留出充足时间，降低 GPU 显存泄漏风险。
- **cancel 信号泄漏**：新增多处 `cancel_flag` 重置点（新请求开始、新 worker 启动、取消完成），防止上一次软取消信号意外中止下一个请求。
- 非隔离模式下 cancel 仅在帧间隙生效，无法中断正在进行的 ONNX/CUDA 单帧推理——补充文档说明。

### 🔧 健壮性改进

- **ffmpeg MP3 转码卡死**：subprocess 调用增加 30 秒超时，防止 ffmpeg 进程无限阻塞合成线程。
- **cancel_flag 异常处理**：`suppress(Exception)` 替换为 `try/except` + debug 日志，便于排查共享内存通信问题。

### 📝 代码质量

- 全量英文注释中文化，技术术语保留英文并加括号。
- kill 模式下进程终止宽限期从 2 秒提升至最少 5 秒，确保 CUDA 上下文有充足时间销毁，降低 GPU 显存泄漏风险（环境变量 `MOSS_PROCESS_KILL_GRACE_SECONDS` / `ANGEVOICE_ENGINE_PROCESS_KILL_GRACE_SECONDS` 仍可自定义，但 kill 路径下限为 5 秒）。

## [2.6.601] - 2026-05-25

### 发布前入口加固

- 正式模板默认启用基础 HTTP 限流与入口容量保护，并新增 WebSocket 连接/消息边界配置，避免公网误暴露时无保护承压。
- 保留 `admin / admin123` 首次进入策略与显著改密提示；源码模式显式关闭 API Key 时在非回环监听地址输出安全警告。
