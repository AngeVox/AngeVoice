# Changelog

## [2.6.601] - 2026-05-25

### 发布前入口加固

- 正式模板默认启用基础 HTTP 限流与入口容量保护，并新增 WebSocket 连接/消息边界配置，避免公网误暴露时无保护承压。
- 保留 `admin / admin123` 首次进入策略与显著改密提示；源码模式显式关闭 API Key 时在非回环监听地址输出安全警告。


### 资源休眠与模型生命周期

- Kokoro 与 ZipVoice 新增可销毁 Worker 进程隔离，正式 Docker/fnOS 模板默认开启；MOSS 保留已验证的隔离实现并统一展示 Worker 状态。
- 管理后台新增 Kokoro/ZipVoice 进程隔离设置、启动预载开关、预载模型选择与 Worker 退出等待设置；隔离关闭时明确提示 RAM 不保证完整回收。
- 默认启动只选择 Kokoro，不再将模型权重预载入 API 主进程；首次生成按需唤醒，用户也可选择通过 Worker 启动预热模型。
- 模型切换时默认释放旧的已加载运行时，减少 Tesla P4 与 NAS 长驻部署中的 RAM/VRAM 叠加占用。

### 兼容性与扩展性

- 修复 ZipVoice runtime 与统一引擎注册层之间的循环导入：注册表仅在实例化 ZipVoice 时延迟导入实际运行时，保留兼容导出但不在模块初始化阶段加载 native engine。
- 为新增模型延续“轻量产品注册 + Worker factory 延迟创建实际 runtime”的扩展边界，避免后续模型接入重新侵入通用路由与资源生命周期。
- 完善三模型隔离运行、Worker 按需启动/退出、模型切换与 WebSocket 流式路径的一致性，确保释放策略可被诊断状态准确反映。

### fnOS / 部署维护

- fnOS/FPK 延用已实机验证的一份 `docker-compose.yaml` + 三个互斥 profile service，通过 `COMPOSE_PROFILES` 选择 CPU、标准 GPU或 Legacy GPU 路径；三类镜像继续使用 `:latest`。
- 正式 Compose 与 fnOS 模板统一启用三模型进程隔离并关闭默认启动预载。
- 部署镜像保持 `:latest` 引用，不将 `2.6.601` 写死到 Docker、FPK 或 CI 镜像选择链路中。

## [2.6.6] - 2026-05-24

### 三模型与统一扩展架构
- 完成 `Kokoro v1.1 Chinese`、`MOSS-TTS-Nano`、`ZipVoice` 稳定产品入口与运行 Provider 分离展示。
- 完成 扩展架构统一层：统一合成/流式契约、Voice Profile 服务、Provider Policy、资源状态和动态参数 schema。

### ZipVoice、网页录音与音色管理
- 新增 ZipVoice CPU 与标准 GPU CUDA 路线，CUDA 失败自动回退 CPU 并可诊断。
- 新增参考试听、分句流式、网页直接录音、Profile 保存/改名/删除/复用与完整性检查。
- Studio 的合成进度、错误与录音权限提醒改为右上角浮动通知；ZipVoice 参考音色管理区支持默认折叠与按需展开。
- ZipVoice 参考录音按官方建议提示使用少于 3 秒的清晰短音频，产品上限放宽为 15 秒；超过建议时警告但不自动裁剪，超过上限才拒绝。

### 管理后台、诊断与更新提示
- 默认登录保留 `admin / admin123` 并提供显著安全提醒；恢复中文管理员用户名；修改后仅持久化哈希凭据。
- 增加 API Key/资产/资源诊断、脱敏证据门槛与轻量版本更新提示。
- 管理后台运行参数按 Kokoro、MOSS-TTS-Nano、ZipVoice、服务与存储、安全访问分组；状态提示使用独立的右上角横向通知样式，避免与 Studio Toast 网格冲突造成中文逐字竖排。

### 稳定性与恢复
- 修复 MOSS 非流式超时后旧 worker 可能持锁导致后续请求无法恢复的问题；正式 Docker/fnOS 模板启用可终止的隔离 worker。
- 加固 Kokoro 加载/卸载与合成并发保护、ZipVoice CUDA 回退状态同步、模型管理器状态访问锁边界。
- 修正生产环境 API Key 与运行配置持久化路径，凭据与配置不再落入输出目录。
- 加固 WebSocket 失败统计与关闭边界、运行配置原子持久化、请求历史清理和空请求校验；根环境变量模板保持纯注释示例，避免复制时意外启用选项。

### 开源许可与致谢
- AngeVoice 项目代码许可由 MIT 统一调整为 Apache License 2.0，与 Kokoro、MOSS-TTS-Nano、ZipVoice 三项核心上游集成对齐。
- 新增标准 `NOTICE` 文件，明确 AngeVoice 版权所有者为 `Copyright 2026 安歌 (ang77712829)`，并随源码、镜像与 fnOS/FPK 包分发。
- 补齐 ZipVoice 致谢与第三方许可归属说明；其他运行时资产仍遵循各自许可证。

### Docker、ARM64 与 fnOS/FPK
- CPU/GPU/Legacy 三画像统一持久化契约；标准 GPU 为 Tesla P4 主路径。
- GitHub Actions 增加 CPU `linux/arm64` 构建，CPU 镜像支持 amd64/arm64 多架构发布。
- fnOS/FPK 采用一个静态 `docker-compose.yaml`，安装向导通过 `COMPOSE_PROFILES` 在 docker-project 创建容器前直接选择 CPU / 标准 GPU / Legacy GPU 服务与镜像，并共享模型、音色、凭据及运行配置持久化目录。


All notable changes to AngeVoice TTS service will be documented in this file.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [2.6.5.3.2] - 2026-05-21

### 🚑 紧急修复
- 修复 MOSS ONNX 自动下载兼容：当 `/app/models/MOSS-TTS-Nano-100M-ONNX` 目录存在但缺少 `browser_poc_manifest.json` 或真实模型资产时，不再直接交给官方 runtime 报 500，而是自动尝试从 `MOSS_MODELSCOPE_REPO` 下载补全。
- 修复 MOSS 资产有效性误判：官方 ModelScope 包里的大权重主要是 `*.data`，部分 `*.onnx` 只有几十 KB。现在会把 `browser_poc_manifest.json` + 真实 `*.data` 权重识别为有效模型，避免下载成功后仍被判定为失败。
- 修复 Kokoro 音色库为空：上游 `kokoro` 下载的音色可能位于 Hugging Face 缓存快照 `snapshots/<sha>/voices`，现在音色列表和本地音色解析都会扫描该目录。
- 新增可选 `MOSS_HF_REPO`，如上游提供 Hugging Face ONNX 仓库可手动填写；默认继续使用 ModelScope 作为 MOSS 模型兼容源。

### 🎤 TTS 后端完整包
- 集成用户提交的 TTS 后端补丁（130 文件），新增 `/v1/tts/capabilities` 端点、`response_encoding=base64` JSON 响应、`/v1/audio/voices?detail=true` 音色详情、`emotion`/`emotion_strength`/`style_prompt` 保留字段。
- 新增 `docs/ANGE_READER_BACKEND_ADAPTER.md` 阅读器接入指南。
- `README.md` / `README_EN.md` 补写新接口文档和 base64 响应示例。
- 英文 docstring 统一翻译为中文（`status.py`、`audio.py`、`ws.py`）。
- 移除已弃用的 `data_url` 字段；为现有阅读器与 API 客户端兼容，保留 `audio`（裸 base64）与 `audio_base64`（可直接播放的 data URL）。
- `TTSRequest.input` 增加 `min_length=1`，空文本在 Pydantic 层即拦截（422）。
- `_model_catalog_snapshot` 复用 engine 变量，避免重复 `get_engine` 调用。
- `audio.py` 函数间补 PEP8 双空行。

### 🔒 安全加固
- Bearer token 解析要求空白分隔符，防止 `Bearerxxx` 误通过；新增 `tests/test_security_auth.py` 安全测试。
- `pyproject.toml` 移除 `asyncio_mode = "auto"` 避免 pytest 警告。

### 📦 模型目录统一
- Docker 默认把宿主机 `models/` 挂载到容器 `/app/models`，Kokoro、Hugging Face 缓存、ModelScope 缓存和 MOSS ONNX 模型统一持久化到一个目录。
- Kokoro 推荐目录改为 `models/models--hexgrad--Kokoro-82M-v1.1-zh`；MOSS 推荐目录改为 `models/MOSS-TTS-Nano-100M-ONNX`。
- 三套 Docker Compose 移除独立 `hf_cache` 与 `moss_models` 挂载，安装脚本会在新目录为空时温和迁移旧缓存。

### 🛠️ Kokoro 音色校验修复
- Kokoro 音色文件校验从粗暴的“低于 10KB 就判无效”改为优先识别 PyTorch zip/pickle 文件头，避免真实小型 `.pt` 被误判。
- Git LFS 指针、HTML/JSON 错误页和极小文本占位符仍会被跳过；同一路径只 warning 一次，避免长文本多段合成时日志刷屏。
- 兼容旧布局 `models/voices`，但新布局优先读取 `models/models--hexgrad--Kokoro-82M-v1.1-zh/voices`。

### 🧭 启动体验
- 新增 AngeVoice 启动横幅，显示版本、监听地址、启用模型、Kokoro/MOSS 模型目录和统一模型根目录。

### 🔧 配置一致性与边界修复
- 将 `.env.prod`、`.env.staging`、根 `.env.example` 与 `docker/angevoice.env` 的 MOSS 生产调优参数重新对齐，避免复制不同 env 文件得到不同音频效果。
- 多 worker 启动环境导出补齐 `ANGEVOICE_IDLE_UNLOAD_CURRENT`，避免多 worker 模式下 idle 是否释放当前模型的配置丢失。
- MOSS 模型目录不再只用“目录非空”判定有效，新增 ONNX/LFS/占位文件识别，避免只有指针文件时误判为已下载。
- 百分比文本规范化改为自然数字读法，例如 `100%` 读作“百分之一百”。
- `docker/entrypoint.sh` 改为 `set -euo pipefail`，并补充 legacy-gpu MOSS CUDA compose 覆盖文件使用说明。
- 英文 README 的配置速查表补齐 MOSS 音频后处理、实时流式、限流和队列变量。
- 文档中 `MOSS_PROMPT_AUDIO_MAX_SECONDS=8` 与 `MOSS_RUNTIME_PAUSE_MAX_MS=350` 等实际默认值已重新对齐。
- 多 worker 启动环境导出继续补齐 `KOKORO_TTS_REQUEST_MAX_BYTES` 与 `KOKORO_VOICE_UPLOAD_MAX_BYTES`，确保请求体/上传大小限制在 worker 中生效。
- `.env.prod`、`.env.staging`、根 `.env.example` 补齐 `MOSS_DEFAULT_VOICE`、WeText、MOSS 文本标准化、CUDA 自检和质量闸门变量说明。
- 修复 `get_engine()` 加载失败清理路径中的旧签名 `unload()` fallback，避免清理异常覆盖原始加载错误。
- 加强 worker 环境变量回归测试，不再只检查单个 idle 变量。

### 🧹 代码质量与回归测试
- 统一 `engine.py` / `config.py` logging 写法，移除 f-string logging，避免关闭 INFO/DEBUG 时仍提前求值。
- 拆开 `EngineManager` 的模型快照和切换返回值，保护 `id/name/backend/provider` 等基础字段不被运行时 metadata 静默覆盖。
- 金额文本规范化支持十亿以上金额，避免 `¥1234567890.50` 这类输入被静默跳过或触发高位读法异常。
- `TTSConfig.get_voices()` 增加目录 mtime 缓存，减少状态接口和前端轮询时重复扫描音色目录。
- 缓存命中/未命中统计和读取路径收敛到同一临界区，降低高并发统计偏差。
- 新增 `tests/test_quality_regressions.py` 覆盖金额、模型快照、音色缓存和缓存统计回归。

---

## [2.6.5.2] - 2026-05-20

### 🔊 MOSS 中英文混排修复
- 新增 `MOSS_MIXED_ENGLISH_POLICY=translate`：默认把常见职场/日常英文词组转成自然中文含义，重点改善 `deadline`、`anxiety`、`self-reflection`、`work-life balance`、`personal growth` 等中英文混排长句导致的停顿、怪声和尾部漂移。
- MOSS 流式路径现在也会压缩异常长静音，减少播放中“像卡住几秒”的听感。
- 默认连续静音压缩上限从 `550ms` 收敛到 `480ms`，更适合 NAS/Tesla P4 长文本流式。
- 保留 `MOSS_MIXED_ENGLISH_POLICY=preserve`，需要严格保留英文原文或专有名词时可手动切换。

### 🛠️ Kokoro 模型资产校验
- 继续保留 2.6.5.1 的 Kokoro Git LFS 指针/错误页/不完整权重校验，避免把 100 多字节的 LFS 指针当模型传给 `torch.load`。

---

## [2.6.5.1] - 2026-05-20

### 🔊 MOSS 生产体验优化
- 默认 MOSS 分段改为 `MOSS_SEGMENT_LENGTH=120`、`MOSS_VOICE_CLONE_MAX_TEXT_TOKENS=56`，优先降低 P4/NAS 上中英文混合长文本尾部变调、卡顿和失真。
- MOSS 流式默认缓冲提高到 `MOSS_STREAM_PREBUFFER_SECONDS=0.75`，队列提高到 `MOSS_STREAM_QUEUE_MAX_ITEMS=8`，减少浏览器播放 underflow 和短抖动造成的断续。
- MOSS 后处理改为更自然的 `MOSS_OUTPUT_TARGET_PEAK=0.86` / `MOSS_OUTPUT_GAIN=0.94`，并把边缘淡入淡出降到 `1.5ms`，避免声音过低、过平和辅音被抹掉。
- 连续静音压缩上限改为 `MOSS_MAX_SILENCE_MS=480`，默认段间停顿和 runtime pause 更保守，减少“卡住几秒”的听感。
- 新增 `MOSS_APPLY_ANGEVOICE_RULES=auto`：中文为主文本使用完整中文规则；中英文混排、URL、版本号、API 名称和英文缩写走温和清理，减少混排文本读坏和卡顿。

### 🛡️ 稳定性与资源释放
- Kokoro 本地权重校验改为统一逻辑：主模型、config 与 voices 音色都会识别 Git LFS 指针、HTML/JSON 错误页和过小的不完整文件，避免把 100 多字节的指针文件传给 `torch.load` 触发 `Weights only load failed` / `Unsupported operand 118`。
- 新增 `MOSS_VRAM_SNAPSHOT_TTL_SECONDS=10`，缓存 CUDA 显存快照，避免长文本流式过程中频繁 `torch.cuda.mem_get_info()` / `nvidia-smi` 查询造成同步卡顿。
- Kokoro 与 MOSS 卸载时额外尝试 `torch.cuda.ipc_collect()`；文档明确说明 `nvidia-smi` 无进程但仍有约 100MiB 占用通常是 NVIDIA 驱动 baseline，不代表模型未释放。
- 保持 MOSS 进程级隔离默认关闭；默认路径优先保证实时流式体验，隔离模式作为 CUDA/ONNX Runtime 卡死排查选项。

### 🧪 测试与文档
- 补充 MOSS 自动文本规则和 VRAM Guard TTL 单测。
- README、API Reference、Model Runtime、Service Profiles、Troubleshooting、MOSS Audio Quality 与 Docker env/compose 默认值重新对齐到生产默认参数。
- 清理源码包中的 `__pycache__` 和 `.pytest_cache`。

---

## [2.6.5.0] - 2026-05-16

### 🎙️ 长文本自然合成
- MOSS 文本分句升级为中英文自然切片：支持中文标点、英文句号/问号/感叹号、段落边界和标题，同时避免切断英文单词、小数、版本号、IP 地址。
- 新增 MOSS 音频自然化后处理：chunk 首尾静音裁剪、异常长静音压缩、非流式拼接 crossfade、runtime pause 上限，降低长文本中的 2-5 秒卡顿、重复读、变调和硬切电流感。
- 默认 `MOSS_SEGMENT_LENGTH=180`、`MOSS_MAX_NEW_FRAMES=320`、`MOSS_VOICE_CLONE_MAX_TEXT_TOKENS=64`，按 NAS/P4/8GB 显存安全档发布；`260+` 的长文本旁白质量档保留为 Admin 预设，不再作为生产默认。
- WebSocket 流式播放器增加首包预缓冲和 buffer underrun 观测；MOSS 默认预缓冲 0.45s，Kokoro 默认 0.25s。
- 新增中文单换行策略 `ANGEVOICE_SINGLE_NEWLINE_POLICY=auto`，自动合并网页/小说复制文本的段内硬换行，保留空行、标题和列表结构。

### 🛡️ 显存与生产稳定性
- 新增轻量 VRAM Guard：合成前检测 CUDA 剩余显存，低于安全阈值时自动使用更保守的分句长度、token 上限和帧预算。
- full codec decode 遇到 ONNXRuntime/CUDA 显存分配失败后进入冷却，并在后续片段优先走增量解码，避免每段都先 OOM 再 fallback。
- HTTP 音频缓存新增总字节上限、长文本跳过缓存和大音频跳过缓存，避免长文本 WAV 堆积占用 NAS 内存。
- MOSS 配置变更后会丢弃或标记待重建已加载 engine；忙碌模型请求结束后自动重建，避免 Admin 显示已保存但旧引擎继续运行。
- 默认空闲 10 分钟释放已加载模型，降低 NAS/家用服务器待机显存和功耗。

### 🧭 Admin 后台重构
- Admin 后台重构为 Dashboard / Models / Tuning / Security / Diagnostics 五个轻量区块，不引入前端构建系统，继续保持 vanilla JS。
- 配置项由统一 schema 生成，支持分组编辑、数值范围校验、预设套用、运行时持久化到 `ANGEVOICE_RUNTIME_CONFIG_FILE` 和 ENV patch 导出。
- 增加 NAS 稳定、均衡推荐、长文本旁白、低延迟流式、克隆质量优先等预设，并在 UI 中区分立即生效、需重启和需重建模型的配置。
- Admin 显示 runtime-config 是否覆盖环境变量，并提供清除持久化配置入口，便于排查 Docker env 修改后不生效的问题。
- Admin 增加显存状态、low-vram/degraded 状态、full decode OOM 次数、缓存字节数、最近请求/失败、模型 active_count 和 pending rebuild 状态。
- 继续保留 Docker/NAS 默认 `admin` / `admin123` 的首次登录体验；公网部署文档明确要求改强密码。

### 🚦 国内部署与模型源站
- `ANGEVOICE_MODEL_SOURCE=auto` 改为先短超时探测 Hugging Face / ModelScope 可达性，再做国家/地区判断，并缓存进程内有效源站，减少国内网络冷启动误判和重复探测。
- 管理后台展示模型源站 mode/effective/country/reachability 信息，可手动切换 `auto` / `modelscope` / `huggingface`。
- `KOKORO_API_KEY=auto` 会首次启动自动生成强随机 API Key 并写入 `ANGEVOICE_API_KEY_FILE`，安装脚本和文档会提示查看路径。

### 🔐 安全与运维
- 新增 `KOKORO_TRUST_PROXY_HEADERS=false`，默认不信任 `X-Forwarded-For` / `X-Real-IP`，避免裸露公网时被伪造绕过限流。
- 新增 `KOKORO_PUBLIC_STATUS_ENDPOINTS`，公网敏感部署可让 `/v1/models`、`/v1/models/current`、`/v1/audio/voices` 也要求 Bearer Token。
- Admin 支持查看/轮换 `KOKORO_API_KEY` 生成的 key；管理后台仅支持 Basic Auth 登录，普通 Bearer API Key 无法登录后台。
- MOSS 克隆参考音频默认裁剪到 `MOSS_PROMPT_AUDIO_MAX_SECONDS=8`，与 Docker、代码默认值和文档口径保持一致。

### 🧪 测试、文档与发布
- 新增 `scripts/analyze_audio_quality.py`，可分析 wav 时长、采样率、声道、峰值、RMS、削波比例、长静音段、最大静音和静音占比。
- 新增/补强分句、音频后处理、Admin schema、VRAM Guard、缓存限制、runtime-config、中文换行策略等单元测试。
- README、README_EN、API Reference、Architecture、Roadmap、Troubleshooting、Docker env/compose 对齐 2.6.5.0 的最终默认值：默认 120，均衡/旁白通过后台预设按需切换。
- Docker CPU/GPU/legacy-gpu compose 默认全部切回 NAS/P4 安全档；legacy CUDA 单独更保守。
- 版本统一为 `2.6.5.0`。

---

## [2.6.4.6] - 2026-05-12

### 维护
- 作为 2.6.5.0 之前的升级基线版本，保留 2.6.4.x 系列的管理后台、小智适配、MOSS 质量优先流式、空闲释放和 Docker/NAS 部署能力。
- 后续 2.6.5.0 在此基础上集中修复长文本自然合成、MOSS 显存保护、Admin 调参持久化、缓存限制和文档默认值对齐问题。

---

## [2.6.4.5] - 2026-05-11

### 🔌 小智适配
- 新增 `xiaozhi/` 适配包，集中放置小智后端适配器、配置示例、一键安装脚本、智控台预设和排障文档。
- 新增 AngeVoice OpenAI 非流式适配器 `xiaozhi/adapters/angevoice.py`，通过 `/v1/audio/speech` 调用 Kokoro 或 MOSS 预设音色，适合作为最快跑通的稳定方案。
- 新增 AngeVoice WebSocket 流式适配器 `xiaozhi/adapters/angevoice_stream.py`，支持 Kokoro 流式、MOSS 预设音色流式，以及配置 `prompt_audio_path` 后的 MOSS 克隆流式。
- 新增 AngeVoice MOSS clone 非流式适配器 `xiaozhi/adapters/angevoice_clone.py`，通过 `/api/tts` multipart 上传固定参考音频。
- 新增 `xiaozhi/scripts/install-xiaozhi-adapter.sh` 一键安装脚本，可安装适配器、patch 小智 `docker-compose_all.yml`、创建参考音频目录、写入示例配置并测试容器连通性。
- 新增 `xiaozhi/manager/presets.yaml` 智控台可复制预设，不修改小智前端源码，避免侵入上游项目。
- 新增小智接入教程、快速开始、MOSS clone 参考音频说明和常见问题文档。

### 🔊 MOSS 听感修复
- MOSS 默认改为质量优先流式：关闭逐帧实时解码，仍通过 WebSocket 分包输出，减少 Web Studio 和小智播放中的电流音、卡顿和 chunk 边界爆音。
- MOSS 后处理新增 DC offset 清理、孤立脉冲修复、片段边缘短淡入淡出，并将默认输出峰值/增益下调到更适合小喇叭和 Opus 链路的 `0.78` / `0.90`。
- 修复 MOSS 对“春花秋月何时了”等句式的 `了` 多音字提示：MOSS 使用“蓼”作为 liǎo 提示，避免读成 le 或 liào；Kokoro 仍使用原来的“瞭”提示。
- 新增 `docs/MOSS_AUDIO_QUALITY.md`，说明 MOSS 质量优先参数、逐帧实时解码取舍和小智播放排障。

### 🛠️ 修复
- 修复小智适配器在 `async def text_to_speak()` 中使用同步 `requests.post()` 可能阻塞事件循环的问题，非流式与 clone 适配器改为 `httpx.AsyncClient`。
- 修复管理后台 Basic Auth 在中文账号/密码、不同浏览器编码场景下可能无法进入或抛出异常的问题，认证比较改为基于原始字节候选的安全比较。
- 修复 admin 相关测试函数错误，补充管理后台认证回归测试。

### 🧪 CI / 发布
- 包版本、项目元数据、OpenAPI 版本和测试目标版本对齐为 `2.6.4.5`。
- GitHub Actions 相关 action 升级到 Node 24 runtime 对应版本，避免 Node.js 20 runtime 弃用警告影响后续 CI。
- CI 与 Docker CPU smoke 已覆盖轻量单测、语法检查、CPU 镜像启动和健康检查。

---

## [2.6.4.4] - 2026-05-11

### 🛠️ 修复
- 修复管理后台账号使用中文时 `secrets.compare_digest` 抛出 500 的问题，现在账号/密码会按 UTF-8 字节做安全比较。
- 修复 MOSS CUDA 进程级隔离流式请求把 `KOKORO_REQUEST_TIMEOUT_SECONDS` 当作整段合成总时长的问题；现在它表示 worker 多久无事件才判定卡死，长文本持续产出音频时不会被误杀。
- 修复 WebSocket 客户端断开或刷新页面后，生产线程可能继续阻塞等待队列导致后续请求卡在“建立流式连接”的问题。
- 修复隔离 worker 被取消/杀掉后 `_loaded` 状态未同步，导致下一次请求没有正确重建 worker 的问题。
- `/health` 增加 `idle` 状态：模型因空闲超时卸载时不再误报 `loading`，Docker healthcheck 将 `ok`/`idle` 都视为可用。
- MOSS 进程级隔离保留为可选能力，但默认关闭；需要硬隔离时可手动开启，开启后超时可 kill worker 子进程并在下次请求重建 runtime。
- 新增手动触发的 Docker CPU smoke workflow，覆盖 `docker compose config`、CPU 镜像构建、容器启动、`/health` 和 `scripts/smoke_test.sh`。
- 修复 e2e 脚本在 `set -e` 下使用 `((PASS++))` / `((FAIL++))` 可能提前退出的问题，计数器改为安全自增写法。
- WebSocket e2e 不再只检查 `started`，现在同时验证 `started`、真实 `audio` 分片和 `done` 完成帧。
- idle unload e2e 增加真实“卸载后再请求自动重载”校验；默认超时时长过长时会明确跳过并提示测试环境设置短超时。
- 内置全局 queue limit 不再依赖 `asyncio.Semaphore._value` 私有字段，改为公开状态的非阻塞并发闸门。
- 默认空闲卸载改为 600 秒，并允许释放当前模型；NAS/家用服务器无人使用时可自动释放显存、降低功耗。

### 🎛️ 管理与部署
- 修复一键安装脚本：`docker compose pull` 成功后不再强制 `--build`，只有拉取失败才本地构建。
- 安装脚本新增 `AngeVoice` 管理命令，支持菜单式安装/更新、重启、停止、卸载和状态查看。
- 安装脚本网络检测扩展到 GitHub、GHCR、Docker Hub 与本机 Docker registry mirror；GHCR 不可达时跳过预构建镜像 pull，减少卡顿。
- 本地源码目录执行安装脚本时会就地安装/更新，不再额外克隆到 `/opt/angevoice`；远程安装无本地项目目录时才使用 `/opt/angevoice`。
- 安装完成后自动读取本机局域网 IP，并输出 Studio、管理后台和 API 文档的完整访问地址。
- 容器发布工作流会同时生成 `latest` 和 `vX.Y.Z` 标签，和 Compose 默认 `latest` 镜像保持一致。
- 新增 `/admin` 管理后台入口，沿用主站视觉风格；默认关闭，开启后必须配置账号密码。
- 主页右上角新增“管理后台”入口，与 API 文档入口保持一致。
- 三套 Docker 画像统一读取 `docker/angevoice.env`，公共默认值按 CPU/NAS 安全场景设计，GPU 与 legacy-gpu 仅覆盖必要差异。
- 新增 `docker/.env.example` 作为用户本地自定义模板。
- 新增 `scripts/install.sh` 一键安装脚本，可检测 Docker/Compose、NVIDIA GPU、GPU 型号、GitHub、GHCR、Docker Hub 与本机 registry mirror，并推荐 `cpu` / `gpu` / `legacy-gpu` 画像。

### 🔊 MOSS 体验优化
- MOSS 默认输出策略改为质量优先：更温和的峰值保护、轻微降低输出增益、加大流式最小分片，减少削峰失真、碎片卡顿和块间响度跳变。
- MOSS 流式阈值文档和默认配置对齐，避免 `MOSS_STREAM_BUDGET_THRESHOLD_*` 含义与实际行为不一致。
- MOSS 推理逻辑已拆分到 `src/kokoro_tts/moss/`：运行时加载、自检、文本分段、prompt audio、流式预算和音频后处理可独立维护。

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
