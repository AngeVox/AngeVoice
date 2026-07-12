# AngeVoice 架构说明 / Architecture

本文档说明 AngeVoice v2.6 的模块化结构。v2.6 的目标不是改变模型能力，而是提升服务端可维护性、可测试性和后续扩展空间。

接口字段、鉴权方式和调用示例集中维护在 [API 参考](API_REFERENCE.md)。

> 统一 Voice Profile、流式协议、资源状态、Provider Policy 与动态参数 schema 的设计见本文及 [新增模型 Adapter 指南](NEW_MODEL_ADAPTER_GUIDE.md)。Kokoro、MOSS-TTS-Nano 与 ZipVoice 的推理实现通过 adapter 接入。

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
├── moss_engine.py        # MOSS-TTS-Nano 引擎调度与兼容入口
├── moss/                 # MOSS runtime、现有隔离 worker、prompt、流式和音频后处理辅助模块
├── workers/              # Kokoro / ZipVoice 通用可销毁 Worker 客户端与子进程入口
├── config.py             # 配置和环境变量
├── cli.py                # angevoice / kokoro-tts CLI
├── static_assets.py      # 统一静态资源内容哈希与原生 ESM import map
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

1. `routes/ws.py` 接收首个 JSON 消息，读取 `text/voice/speed/format/binary/token`，并在 MOSS 克隆请求中接收可选 `prompt_audio` base64。
2. `security.py` 校验 WebSocket token 或 Authorization header。
3. `service_state.py` 用同一个并发信号量保护推理。
4. `engine_manager.py` 借用目标模型，当前模型不匹配且启用卸载策略时会先切换并卸载旧模型。
5. 引擎生成 `started/audio/segment_error/done` 消息。Kokoro 保持上游 pipeline 的段落级推理，但在 WebSocket 发送前按固定时长切成小包；MOSS 默认使用官方逐帧回调和 codec streaming decoder（`MOSS_REALTIME_STREAMING_DECODE=true`），保持低延迟流式体验；若特定设备出现边界噪声或显存压力，可在后台关闭逐帧流式。
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
- `moss`：MOSS-TTS-Nano 产品入口；OpenMOSS 官方 runtime 的 CPU/CUDA 由 Provider Policy 决定，旧 `moss-nano-cpu` / `moss-nano-cuda` 仅作为兼容输入 alias。

正式 Docker/fnOS 模板中，Kokoro、MOSS-TTS-Nano 与 ZipVoice 均通过可销毁 Worker 加载推理运行时；API 主进程仅持有路由、配置、Voice Profile 元数据与状态。模型切换时只保留一个活跃热 Worker，空闲释放或取消/超时时退出 Worker，使操作系统回收其 RAM 与 VRAM。库级调用仍允许关闭隔离以保持兼容。MOSS CUDA 加载会先检查 ONNX Runtime provider，并在启用质量闸门时生成短音频，拒绝静音、NaN/Inf 或明显 clipping 的输出。MOSS 流式取消使用软取消和 request_id 过滤，避免停止后旧帧污染下一次合成；长文本首帧或分段间隙通过独立流式空闲窗口保活，避免被普通请求超时误断开。

`MOSS_CUDA_ENABLED=false` 会禁止 `moss` 请求 CUDA provider，用于 CPU 镜像和 legacy-gpu 默认配置。标准 GPU 画像公开模型仍为 `kokoro,moss,zipvoice`，但允许 MOSS 使用 CUDA；`ANGEVOICE_DEFAULT_MODEL=kokoro`，因此 MOSS 只会在用户切换时加载。

MOSS capability metadata 会声明 `modes=["preset_voice","voice_clone"]` 和 `voice_clone_supported=true`。Studio Web UI 根据该能力显示参考音频上传控件；非克隆模型收到 `prompt_audio` 时会返回 400。HTTP 缓存 key 包含模型 ID 和参考音频指纹，避免不同 prompt audio 误命中同一条缓存。

MOSS 适配层不会直接改写上游仓库代码。AngeVoice 在适配层中做四件事：复用单个 MOSS executor 并用 runtime lock 保护官方 runtime；对 clone 参考音频做时长裁剪和 prompt code LRU 缓存；对输出做温和峰值保护，降低 8GB 显存环境下 clone OOM、爆音和削波的概率；保留可选进程级隔离能力，便于排查 CUDA/ONNX Runtime 底层卡死问题。

进程级隔离在 Docker/fnOS 正式部署模板中对三种模型默认开启：MOSS 将 CPU 与 CUDA provider 放入现有隔离 Worker；Kokoro 与 ZipVoice 通过通用 `workers/process_worker.py` 子进程运行。非流式与流式请求在超时、取消或底层卡死后均可终止对应 Worker，并在下次请求按需重建。库级配置仍保留关闭隔离的能力，供嵌入式调用者自行权衡，但关闭后主机内存不保证在释放时完整归还。可选的 `ANGEVOICE_RESTART_AFTER_IDLE_UNLOAD=true` 只在模型因空闲卸载成功、且没有活跃请求/WebSocket/已加载模型时退出 API 进程，交给容器或服务管理器拉起，用于清理 CUDA/ONNX Runtime 底层残留。

MOSS CUDA 依赖目标环境的 ONNX Runtime/CUDA/cuDNN 组合。通用 GPU Docker 画像使用 `onnxruntime-gpu==1.20.2` + `nvidia-cudnn-cu12==9.1.0.70`；缺 cuDNN 9 时官方 runtime 会创建 CPU session，AngeVoice 会拒绝该 CUDA 加载并按配置回退 CPU。legacy-gpu 镜像通过 ONNX Runtime CUDA 11 feed 预装了 CUDA 11.8 兼容的 MOSS GPU 依赖，但默认只开放 MOSS CPU；它是通用 GPU 画像无法启动或不稳定时的兼容模式。


### MOSS 子模块

`kokoro_tts.moss` 子包承载从 `moss_engine.py` 拆出的纯逻辑和隔离逻辑：

| 文件 | 职责 |
|---|---|
| `runtime.py` | 官方 runtime 导入、provider 创建、CUDA 显存限制注入、自检音频分析 |
| `process_worker.py` | 可选 MOSS 进程级隔离；父进程调度，worker 子进程加载 runtime 并执行推理 |
| `prompt.py` | 参考音频裁剪、采样率/通道对齐、prompt code LRU 缓存 |
| `streaming.py` | 流式帧预算、codec streaming 输出整理 |
| `postprocess.py` | 波形归一化、温和峰值保护、静音和流式分片 |
| `text.py` | MOSS 文本清洗和分段 |

正式部署模板默认启用 Kokoro、MOSS 与 ZipVoice 进程隔离，并设置 `MOSS_PROCESS_ISOLATION_PROVIDERS=cpu,cuda`；默认关闭启动预载，首次生成时按需唤醒。库级默认仍保持兼容关闭，避免未使用部署模板的嵌入式调用无意改变运行方式。

## Studio Web UI

`routes/status.py` 的首页路由会注入 bootstrap JSON，包含音色列表、默认音色、最大文本长度、采样率、认证和流式能力。前端静态资源由 `/static/app.css` 和 `/static/app.js` 提供，不需要额外构建步骤。

`static_assets.py` 在应用装配时为所有打包资源计算 LF 标准化的内容哈希；模板通过同一个 manifest 生成 CSS 和入口模块 URL，并注入覆盖全部原生 ESM 模块的 import map。JavaScript 源码只保留普通相对 import，不再人工维护递归查询参数，同时仍可由 Node 直接执行 ESM smoke。

共享 i18n runtime 从 `static/locale/common`、`static/locale/studio` 和 `static/locale/admin` 合并互不重叠的分域词典；重复 key 会在模块初始化时失败，而不是按加载顺序静默覆盖。需要保留 `<code>`、链接或动态强调节点的文案使用 `data-i18n-template` 与命名 DOM slot：catalog 只保存纯文本和 `{slot}`，runtime 只拼接 TextNode 与受控节点，不解析翻译 HTML。

Studio 的模型/Provider/音色展示模块保持纯函数边界：技术 ID 和用户命名原样返回，本地化状态通过调用方提供的 translator 或稳定 presentation key 解析。Toast 与进度条保存 `{key, params}` 描述符，因此切换语言可重绘瞬时文案；编辑区默认示例只在用户尚未输入时随语言切换，不能覆盖未保存内容。`tests/quality/studio_copy_debt.json` 是精确、分类且只允许缩减的迁移 ratchet；scanner 独立遍历模板和所有 `static/studio/**/*.js`，新硬编码用户文案、动态翻译 key 或过期债务条目都会失败。Phase 1 退出前该债务表必须清零，schema/error 边界只能通过稳定 key/code 合同消除，不能扩大路径 allowlist。

启用 `KOKORO_API_KEY` 时，Studio 设置面板保存的 Bearer Token 会同时用于 HTTP 请求和 WebSocket 首个 JSON 消息。

当所选模型支持 `voice_clone` 时，Studio 显示参考音频上传控件。HTTP 合成使用 multipart 上传；WebSocket 流式会把参考音频转成 base64 放入首个 JSON 消息，后端复用同一套校验、临时文件和 MOSS prompt 缓存逻辑。

## 包名与模型加载关系

发行包名改为 `angevoice` 不会影响 Kokoro 模型加载。模型加载主要依赖：

- 上游 Python 包：`kokoro`
- Hugging Face repo：`hexgrad/Kokoro-82M-v1.1-zh`
- 本地模型文件：`models/models--hexgrad--Kokoro-82M-v1.1-zh/kokoro-v1_1-zh.pth`
- 本地配置文件：`models/config.json`
- 音色目录：`models/models--hexgrad--Kokoro-82M-v1.1-zh/voices/*.pt`

项目品牌名、发行包名和 CLI 名称不参与模型权重解析。


MOSS 使用独立分段长度 `MOSS_SEGMENT_LENGTH`（默认 120），不再强制复用 Kokoro 的 `KOKORO_SEGMENT_LENGTH`。这样 Kokoro 可以保持自己的分段策略，而 MOSS 优先降低中英文混合尾部漂移、卡顿和失真。Admin 后台保存的运行时配置会写入 `ANGEVOICE_RUNTIME_CONFIG_FILE`，默认 `/app/config/runtime-config.json`，在环境变量之后加载。


## ZipVoice GPU Provider 与自动回退

CPU 路线使用 `zipvoice-distill-onnx-int8` CPU runtime。标准 `gpu` 画像提供 `zipvoice-distill-pytorch-cuda` 请求路径，并以 `ZIPVOICE_AUTO_FALLBACK_CPU=true` 保留 CPU runtime。模型状态必须同时暴露 `requested_provider`、`actual_provider`、`fallback` 与 `fallback_reason`；运行状态通过 `requested_provider`、`actual_provider` 与 `fallback_reason` 明确展示；部署者可通过诊断接口观察长文本、流式取消与资源表现。`legacy-gpu` 不启用 ZipVoice CUDA，只作为标准 `gpu` 无法运行时的兼容模式。
