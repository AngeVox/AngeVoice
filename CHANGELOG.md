# 更新日志 (CHANGELOG)

## v1.1 (2026-05-02)

### 新增功能
- **CORS 中间件**：添加跨域资源共享支持，允许第三方应用（如 Tavern AI、Web 前端等）直接调用 API
- **环境变量配置**：新增 `KOKORO_MODEL_DIR` 环境变量，支持自定义模型文件路径，无需修改代码
- **CPU + GPU 双版本**：同时提供 CPU 和 GPU 两个版本，用户可根据硬件环境自由选择

### 改进与修复
- **torch 线程保护**：添加 `torch.set_num_interop_threads` 的 try/except 保护，避免重复设置导致 RuntimeError
- 使用环境变量 `KOKORO_MODEL_DIR` 替代原有的 monkey patch 方式配置模型路径，代码更优雅

---

## v1.0 (2026-02-21)

### 初始版本发布
- **中文 + 英文语音合成**：基于 Kokoro-82M-v1.1-zh 模型，支持中英文文本转语音
- **多种声音模型**：内置多种中文/英文声音模型（如 `zf_001`、`af_maple` 等）
- **语速调节**：支持通过 API 参数调整合成语速
- **Docker 部署**：提供 CPU 和 GPU 两个 Docker 配置，一键部署
- **OpenAI 风格 API**：兼容 OpenAI TTS API 调用格式，方便集成到现有系统
- **RESTful API**：提供标准 HTTP 接口，支持 Tavern AI 等第三方应用集成
- **一键启动脚本**：`run-tts.py` 自动检测环境并安装依赖
