# Changelog

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
- Docker 环境变量 `MOSS_PROCESS_KILL_GRACE_SECONDS` 和 `ANGEVOICE_ENGINE_PROCESS_KILL_GRACE_SECONDS` 默认值从 2 调整为 5。

## [2.6.601] - 2026-05-25

### 发布前入口加固

- 正式模板默认启用基础 HTTP 限流与入口容量保护，并新增 WebSocket 连接/消息边界配置，避免公网误暴露时无保护承压。
- 保留 `admin / admin123` 首次进入策略与显著改密提示；源码模式显式关闭 API Key 时在非回环监听地址输出安全警告。
