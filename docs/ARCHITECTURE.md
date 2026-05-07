# AngeVoice 架构说明 / Architecture

本文档说明 AngeVoice v2.5 的模块化结构。v2.5 的目标不是改变模型能力，而是提升服务端可维护性、可测试性和后续扩展空间。

## 设计目标

- 保留 `kokoro_tts.server.create_app()` 与 `run_server()` 对外入口。
- 保留 `kokoro_tts` import 包名，避免破坏旧脚本。
- 新增 `angevoice` CLI，同时保留 `kokoro-tts` 兼容命令。
- 将原本集中的 `server.py` 拆成状态、鉴权、数据模型和路由模块。
- 批量、管理、MP3 等扩展继续通过 `service_extras.py` 注册。
- 内置 Studio Web UI 拆分为模板和静态资源，便于 Docker 热更新与包分发。
- 中文文本规则独立放入 `zh_rules.py`，避免把分词/多音字逻辑散落在引擎内。
- 通过 `engine_manager.py` 管理可选模型引擎，默认保持 Kokoro，MOSS-TTS-Nano 通过官方运行时适配。

## 模块布局

```text
src/kokoro_tts/
├── server.py             # FastAPI app factory，只负责装配
├── service_state.py      # 运行时状态、缓存、统计、请求队列、合成调度
├── security.py           # HTTP Bearer 与 WebSocket token 校验
├── api_models.py         # Pydantic 请求模型
├── routes/
│   ├── status.py         # /, /health, /stats, /requests, voices, cancel
│   ├── audio.py          # /v1/audio/speech, /api/tts
│   └── ws.py             # /ws/v1/tts
├── service_extras.py     # batch/admin/mp3 扩展接口
├── zh_rules.py           # 中文断句、多音字、轻量分词规则
├── audio.py              # 音频编码工具
├── engine_manager.py     # 模型注册、加载、切换、卸载
├── engine.py             # Kokoro 引擎、分段、文本规范化、音频编码
├── moss_engine.py        # MOSS-TTS-Nano 官方 ONNX runtime 适配器
├── config.py             # 配置和环境变量
├── cli.py                # angevoice / kokoro-tts CLI
├── templates/index.html  # Studio Web UI HTML shell
└── static/               # Studio Web UI CSS/JS
```

## 请求路径

### HTTP 合成

1. `routes/audio.py` 接收 `/v1/audio/speech` 或 `/api/tts` 请求。
2. `api_models.py` 校验 OpenAI 风格请求体。
3. `service_state.py` 记录 request id、排队状态、统计和缓存。
4. `service_state.py` 根据请求中的 `model` 借用当前引擎；切换模型时缓存 key 会按模型隔离。
5. `routes/audio.py` 在 MOSS 克隆请求中接收 `prompt_audio` multipart 文件，做后缀、大小校验并生成缓存指纹。
6. `engine.py` / `moss_engine.py` 都走共享的中文文本规范化入口，调用 `zh_rules.py` 做中文标点、时间读法、轻量语义匹配和多音字规则；Kokoro 再分段调用 pipeline，MOSS 则调用官方 ONNX runtime。
7. `service_state.py` 可按 `ANGEVOICE_SAVE_OUTPUTS` 把 HTTP 合成结果写入持久化输出目录。
8. `routes/audio.py` 返回 `StreamingResponse`，响应头包含 `X-Request-ID`。

### WebSocket 流式

1. `routes/ws.py` 接收首个 JSON 消息，读取 `text/voice/speed/format/binary/token`。
2. `security.py` 校验 WebSocket token 或 Authorization header。
3. `service_state.py` 用同一个并发信号量保护推理。
4. `engine_manager.py` 借用目标模型，当前模型不匹配且启用卸载策略时会先切换并卸载旧模型。
5. 引擎逐段生成 `started/audio/segment_error/done` 消息。
6. 客户端发送 `cancel` 或 `stop` 后，服务停止后续段落推送。

## 状态对象

`ServiceState` 是当前进程内的运行时状态中心，包含：

- `tts_semaphore`：推理并发限制。
- `tts_cache`：内存 LRU 音频缓存。
- `active_requests`：最近请求状态。
- `cancelled_requests`：取消标记集合。
- `stats`：基础统计计数。
- `model_manager`：进程内模型注册表和当前模型状态。
- `output_lock`：保护持久化输出写入和数量裁剪。

`tts_cache` 使用线程锁保护，因为同步合成路径会在线程池中运行，多请求并发时会同时读写 LRU 缓存。

这些状态是进程内状态。如果使用多个 worker，每个 worker 会有独立状态、独立模型和独立缓存。多模型热切换建议 `KOKORO_WORKERS=1`，尤其是 GPU/NAS 环境。`run_server()` 在 `KOKORO_WORKERS>1` 时使用 Uvicorn import string + factory 模式启动，避免多 worker 启动失败。

## 多模型运行时

`EngineManager` 负责把请求中的 `model` 解析到具体引擎：

- `kokoro`：默认 Kokoro v1.1 中文引擎。
- `moss-nano-cpu`：OpenMOSS 官方 ONNX runtime + CPUExecutionProvider。
- `moss-nano-cuda`：OpenMOSS 官方 ONNX runtime + CUDAExecutionProvider，实验模式。

模型切换 API 会在同一进程内加载目标模型，并在 `ANGEVOICE_MODEL_UNLOAD_ON_SWITCH=true` 时卸载旧模型、清理缓存。MOSS CUDA 加载会先检查 ONNX Runtime provider，并在启用质量闸门时生成短音频，拒绝静音、NaN/Inf 或明显 clipping 的输出。

`MOSS_CUDA_ENABLED=false` 会在注册阶段隐藏 `moss-nano-cuda`，用于 CPU 镜像和 legacy GPU 默认配置。通用 GPU 画像默认注册 `kokoro,moss-nano-cpu,moss-nano-cuda`，但 `ANGEVOICE_DEFAULT_MODEL=kokoro`，所以 MOSS 只会在用户切换时加载。

MOSS capability metadata 会声明 `modes=["preset_voice","voice_clone"]` 和 `voice_clone_supported=true`。Studio Web UI 根据该能力显示参考音频上传控件；非克隆模型收到 `prompt_audio` 时会返回 400。HTTP 缓存 key 包含模型 ID 和参考音频指纹，避免不同 prompt audio 误命中同一条缓存。

MOSS CUDA 依赖目标环境的 ONNX Runtime/CUDA/cuDNN 组合。Tesla P4 在通用 GPU Docker 画像中已通过 `onnxruntime-gpu==1.20.2` + `nvidia-cudnn-cu12==9.1.0.70` 探针测试；缺 cuDNN 9 时官方 runtime 会创建 CPU session，AngeVoice 会拒绝该 CUDA 加载并按配置回退 CPU。Legacy GPU 镜像通过 ONNX Runtime CUDA 11 feed 预装 CUDA 11.8 兼容的 MOSS GPU 依赖，但默认只开放 MOSS CPU，方便用户先稳定运行 Kokoro。

## Studio Web UI

`routes/status.py` 的首页路由会注入 bootstrap JSON，包含音色列表、默认音色、最大文本长度、采样率、认证和流式能力。前端静态资源由 `/static/app.css` 和 `/static/app.js` 提供，不需要额外构建步骤。

启用 `KOKORO_API_KEY` 时，Studio 设置面板保存的 Bearer Token 会同时用于 HTTP 请求和 WebSocket 首个 JSON 消息。

当所选模型支持 `voice_clone` 时，Studio 显示参考音频上传控件。选择文件后前端会自动使用 HTTP multipart 生成，并关闭 WebSocket 流式开关，因为 WebSocket 首包不承载音频文件。

## 包名与模型加载关系

发行包名改为 `angevoice` 不会影响 Kokoro 模型加载。模型加载主要依赖：

- 上游 Python 包：`kokoro`
- Hugging Face repo：`hexgrad/Kokoro-82M-v1.1-zh`
- 本地模型文件：`models/kokoro-v1_1-zh.pth`
- 本地配置文件：`models/config.json`
- 音色目录：`models/voices/*.pt`

项目品牌名、发行包名和 CLI 名称不参与模型权重解析。
