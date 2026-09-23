# AngeVoice 测试与质量门禁

本文定义项目测试层、可复现环境和代码演进必须遵守的运行方式。

债务状态以 [架构债务台账](ARCHITECTURE_DEBT.md) 为准。历史 P 编号不决定当前测试是否齐全，也不代表真实模型已经验收。

## Python 3.12 环境

使用 Python 3.12 创建仓库内虚拟环境：

```powershell
uv venv .venv --python 3.12
uv pip sync requirements/test.lock --python .venv\Scripts\python.exe
uv pip install -r requirements/test-torch-cpu.lock --python .venv\Scripts\python.exe
uv pip check --python .venv\Scripts\python.exe
uv pip install -e . --no-deps --python .venv\Scripts\python.exe
```

这里的 `uv pip check` 位于 `pip install -e . --no-deps` 之前，因此它只验证已经锁定的轻量 CI 测试环境彼此一致；它不验证 AngeVoice 完整项目依赖是否齐全，不能报告为“完整项目依赖一致性已验证”。

`requirements/test.lock` 是 Python 3.10–3.12 通用的轻量测试锁；`requirements/test-torch-cpu.lock` 将 Torch 固定为 Docker CPU 画像的安全基线 `2.13.0`。GPU/legacy-gpu 为保留旧硬件兼容暂用 `2.6.0`，不再声称三画像版本相同；风险与安装组合见 [依赖安全基线](DEPENDENCY_SECURITY.md)。更新输入文件后必须重新生成并提交锁文件：

```powershell
uv pip compile requirements/test.in --universal --python-version 3.10 --generate-hashes --output-file requirements/test.lock
uv pip compile requirements/test-torch-cpu.in --universal --python-version 3.10 --generate-hashes --emit-index-url --output-file requirements/test-torch-cpu.lock
```

## 测试层

| 层 | 位置或 marker | 用途 | 默认 CI |
| --- | --- | --- | --- |
| Quality | `tests/quality/**` / `quality` | 复杂度、依赖方向、i18n、锁文件和治理约束 | 独立前置 job |
| Contract | `tests/contracts/**` / `contract` | 配置优先级、生命周期、公开载荷和 adapter 边界 | 是 |
| Unit | 其余不依赖真实模型的测试 | 纯逻辑和单模块行为 | 是 |
| Integration | `integration` | FastAPI、WebSocket、进程协议、Docker 配置 | 是，真实模型除外 |
| Model smoke | `model_smoke`、`scripts/smoke_test.sh`、`scripts/e2e_loop_test.sh` | 真实权重、音频输出、CPU/GPU/provider 行为 | 画像环境按需运行 |

### 合同的三种用途

- **长期行为合同**：保护输入/输出、优先级、错误类型、取消和资源生命周期。通过可观察行为断言，不绑定 private helper 名称、字面量摆放或函数体布局。
- **历史行为记录**：复现已有兼容行为或已知缺陷，docstring 必须说明限制。缺陷被正式修复时，在原合同中升级为目标行为断言，保留原始 RED 证据；不得让“旧缺陷必须存在”阻止修复。
- **依赖方向/安全边界检查**：只对明确的 owner、禁止反向 import、公开接口泄漏或敏感输出实施必要静态约束。不能把合法实现方式锁成唯一 AST 形状。

新增测试按领域和行为命名，优先扩展已有合同并保留兼容覆盖。`test_text_preparation_boundary_contract.py` 保留历史 CURRENT/FUTURE 名称，作为冻结边界基线不直接编辑；进程传输行为在 `test_text_preparation_process_integration.py` 中维护。测试名称不决定行为是否已经实现。

### 领域归属索引

| 领域 | 主要测试入口 | 维护职责 |
| --- | --- | --- |
| 请求文本准备 | `tests/contracts/test_text_preparation_boundary_contract.py`、`tests/test_text_frontend_recovery_tn.py` | service-selected TN、raw/prepared、MOSS runtime flags |
| 文本进程传输 | `tests/test_text_preparation_process_integration.py` | 真实 spawn、父端转发、连续请求无 prepared 状态泄漏；使用替身 runtime |
| 引擎和资源生命周期 | `tests/contracts/test_engine_adapter_conformance_contract.py`、`test_engine_manager_concrete_dependency_contract.py`、`test_shutdown_lifecycle_contract.py` | Adapter 一致性、构造 owner、shutdown admission/drain/retry |
| Worker 协议与失败 | `tests/contracts/test_engine_worker_spec_contract.py`、`test_engine_error_worker_failure_envelope_contract.py`、`test_worker_load_failure_lifecycle_contract.py`、`test_process_topology_config_inheritance_contract.py`、`tests/test_worker_shutdown_process_integration.py` | 序列化、code/message、加载事务、关闭回执与真实 spawn 恢复 |
| 配置与模型来源 | `tests/contracts/test_model_source_detect_policy_contract.py`、`test_model_source_executor_fallback_contract.py`、`test_model_source_revision_credential_offline_contract.py`，`tests/test_model_source_probe.py`、`tests/test_runtime_config_process_integration.py`，以及各领域 metadata 合同 | ENV/Admin 投影、优先级、跨进程配置写入、来源选择、HTTP 重定向和下载兼容 |
| 流、取消与 WS | `tests/contracts/test_stream_event_error_transport_contract.py`、`test_request_cancellation_resource_ownership_contract.py`、`tests/test_ws_cancel_characterization_2615.py` | 结束事件、错误传输、迭代器关闭及断连释放 |
| 前端与文档页面 | `tests/test_api_docs_i18n.py`、`tests/test_api_docs_browser.py`、`tests/quality/test_i18n_contract.py`，以及 Studio/Admin 行为测试 | 翻译和状态保持、静态资源、浏览器与 wheel |

表内省略目录的合同文件均位于 `tests/contracts/`。精确节点名以 pytest collection 为准；新增覆盖应更新本索引，而非另建工单型测试框架。

常用命令：

```powershell
# 最快的架构与 i18n 门禁
.venv\Scripts\python.exe -m pytest -q tests/quality

# 重构边界合同
.venv\Scripts\python.exe -m pytest -q tests/contracts

# 默认完整测试与覆盖率下限
.venv\Scripts\python.exe -m pytest -q --cov=kokoro_tts --cov-report=term-missing --cov-fail-under=70
```

## 当前行为保护映射

| 重构边界 | 已有保护 |
| --- | --- |
| 三模型产品 ID、Provider 和能力声明 | `test_product_model_registry.py`、`test_product_features_packaging.py`、`test_zipvoice_cpu_runtime.py`、`tests/contracts/test_foundation_contracts.py` |
| EngineManager load/switch/unload/status | `test_basic.py::TestEngineManager`、`test_product_model_registry.py`、`tests/contracts/test_foundation_contracts.py` |
| worker 正常流、取消、超时、关闭、完成帧、子进程入口 | `test_security_hardening.py`、`test_v26601_hardening.py`、`test_zipvoice_preparation_boundary_recovery.py` |
| WebSocket 首包、认证、停止、断连、finally cleanup | `test_security_hardening.py`、`test_ws_cancel_characterization_2615.py`、`test_docker_integration.py` |
| 配置默认值、ENV、runtime config、调用参数优先级 | `test_basic.py::TestConfig`、`test_admin_config_schema.py`、`test_v26601_hardening.py`、`tests/contracts/test_foundation_contracts.py` |
| HTTP/status/resource 载荷 | `test_status_routes_characterization_2615.py`、`test_service_state_characterization_2615.py`、`test_extension_architecture.py` |
| i18n 分域键、占位参数、安全 DOM slot、动态 key 证明与硬编码 copy ratchet | `tests/quality/test_i18n_contract.py`、`tests/quality/studio_copy_debt.json`、`test_i18n_runtime.py` |
| 静态资源 content hash、ESM import map 与递归 wheel 打包 | `test_static_asset_manifest.py`、`test_i18n_runtime.py`、`test_studio_model_presentation.py` |
| Studio 录音 PCM/WAV、权限失败、手动/自动停止和资源释放 | `test_studio_recording.py`、`test_product_features_packaging.py` |
| Studio 参考试听请求取消、迟到响应隔离、WAV MIME、Object URL 与媒体错误释放 | `test_studio_reference_audio_preview.py`、`test_product_features_packaging.py` |

## 领域测试维护要点

MOSS VRAM 生命周期在 `test_moss_characterization_2615.py` 使用可控时钟与合成探测快照验证：首次失败也遵守 TTL，无历史快照的 OOM 保留保守限制至 TTL；探测失败保留最后成功快照，force 与零/负 TTL、阈值等号、CPU/禁用、卸载重置均有覆盖。没有真实 CUDA 探测或推理，不把策略正确性当作显存画像验收。探测时机是现有 `moss.vram` 的纯判断，引擎继续持有快照、低显存状态和独立 full-codec 冷却。

MOSS 隔离流转发/关闭继续在 `test_request_cancellation_resource_ownership_contract.py` 演进：事件对象原样转发，done/error/segment_error/cancelled 不重复修复，缺失终止帧时关闭底层迭代器后报告下一音频索引。`yield from` 必须把上层提前关闭传递到转发层的 finally；既有普通关闭异常、BaseException、内部失败和取消行为断言保留。静态资源归属检查跟随实际 owner 更新，不替代这些行为测试。Manager 测试创建的空闲 timer 必须在 fixture teardown 停止并等待退出，不能通过过滤后续安全日志断言掩盖泄漏。

模型来源执行行为继续在 `test_model_source_executor_fallback_contract.py`、`test_model_source_revision_credential_offline_contract.py` 和 `test_kokoro_managed_asset_integrity.py` 演进。MOSS 模型/tokenizer 共用执行循环，但入口各自选择计划和校验器；SDK 返回目录先于目标目录校验，原有 ModelScope fallback 和 Hugging Face 异常边界保留。Kokoro 单独验证受管目录准入、预置 revision/摘要、失败关闭及普通目录懒加载回退，不把两类策略合并。这些测试不验证下载原子性或真实模型推理。

### 覆盖率与执行顺序

CI 覆盖率下限为 70%，具体覆盖率随平台和候选变化，以该次 Gate 的 coverage JSON 和完整命令为准，不把历史百分比当作当前事实。每次有意义的实现需要比较同环境基线及变更路径覆盖，不能仅满足下限；跨平台稳定证据齐备后再单独收紧全局阈值。复杂度热点由 `tests/quality/test_architecture_ratchets.py` 执行逐函数只降不升规则，函数下降后应同步降低或移除其 ratchet 项。

先跑变更相关合同、security 和 quality，在实现批次或最终累计候选运行完整套件。候选与风险未变化时复用已通过证据；纯文档修正不重复全量运行。测试失败、外部 runner 错误和缺少模型环境必须分别记录。日志、临时目录、coverage 和构建产物放在仓库外，保存真实命令/退出码，并使证据包覆盖 tracked/untracked 候选内容。

涉及标准库行为的修改，至少在最低支持版本 Python 3.10 和当前 CI 最高版本 3.12 运行相关合同；单个本地版本通过不能替代 CI 3.10/3.11/3.12 矩阵。模型来源探测的 308 重定向在 Python 3.10 需要显式兼容，由 `tests/test_model_source_probe.py` 验证 HEAD/GET、非法目标、循环限制和响应关闭。两份测试锁文件按 CI 顺序分步安装，避免 Torch 专用索引覆盖轻量依赖的索引。

全局覆盖率不能代替关键路径合同。MOSS、worker、WebSocket 等硬件或并发相关代码即使受平台影响无法获得高行覆盖率，也必须通过明确的协议、取消、超时和资源释放测试保护。

## 浏览器与真实模型 smoke

Studio、Admin 和 API Docs 已完成本地化实现及历史浏览器验收，Admin 包括动态 metadata。Playwright 目前不进入默认 CI；涉及前端模块或本地化的变更必须重新验证相关页面的 `zh-CN -> en` 切换、`localStorage` 持久化和刷新恢复，不能把历史截图当作新候选的浏览器证据。

Studio 动态文案的浏览器 Gate 还必须验证：模型/音色/能力状态在切换语言后重新渲染，已有 Toast/进度描述符同步换语言，默认示例文本可本地化但用户已编辑内容保持不变。语言选择器中的本名、模型/Provider/音色 ID 和用户命名属于数据，不作为混合语言缺陷；除此之外的可见固定文案必须进入 catalog 或精确登记在只降不升的 copy debt 中。

涉及静态资源或模块图的改动还必须验证三个页面输出的 import map、全部请求 URL 的 12 位内容哈希、module/CSS 200、无 404/console error/pageerror，并构建 wheel 确认 `static/**/*` 中的新模块确实被打包。

真实模型 smoke 由部署画像运行，不能伪装成无权重单元测试：

```bash
# Kokoro 为必测；MOSS 在可用时运行；ZipVoice 使用已保存 Voice Profile。
ZIPVOICE_SMOKE_VOICE=voice_001 bash scripts/e2e_loop_test.sh http://127.0.0.1:8101 "$API_KEY" 3
```

该脚本的真实模型 smoke contract/harness 已定义：它要求验证 Kokoro HTTP/WebSocket、MOSS 可用 Provider、ZipVoice 已保存音色、取消恢复、可选空闲卸载和短循环稳定性。缺少模型或 ZipVoice Voice Profile 时会明确记为 SKIP，不能报告为通过。定义 harness 不等于已执行或已通过；只有在含真实权重的画像运行后，才能声明真实模型 smoke 已执行或通过。

WS 首包失败与参考文件清理、输入别名、二进制元数据/音频顺序的长期行为回归继续在 `tests/test_ws_cancel_characterization_2615.py` 演进。文件名保留历史来源，不代表新增断言只描述历史缺陷；当前合同要求参数错误保留结构化载荷。

配置执行顺序继续由 `tests/contracts/test_config_env_contract.py` 和 facade 合同覆盖：路径/标量先于凭据生成、生成失败的部分写入状态、根目录与显式子目录优先级、runtime 与显式调用覆盖。新增领域修改应在这些行为合同演进，不依赖 helper 名称或函数行数。

B1 的路径字符串展开、Path 对象身份、ZipVoice 消费方路径保留在 `test_ttsconfig_facade_contract.py` 验证；Admin ENV 主/旧名称回退、空值及空白、持久化文件存在、禁用后台、占位符拒绝顺序和日志归属在 `test_security_hardening.py` 验证。历史 P2A1 JSON 快照保持原样，当前 ENV reader 迁移在原归属合同中显式映射，不改历史快照或放宽 hash 门槛。`admin_auth` 原有函数导出保留，轻量 bootstrap 模块不引入 FastAPI/Torch 依赖。

## 运行时与并发合同索引

ZipVoice 共用合成路径在 `tests/test_zipvoice_cpu_runtime.py` 中参数化覆盖 CPU/CUDA 包装器，包含参数夹取、参考校验、FLOAT→PCM16、失败清理与 CUDA 专属参数。该文件保留历史名称；替身测试不证明真实 CUDA 推理或音质。provider fallback 继续由 `tests/test_zipvoice_gpu_provider.py` 维护。

ZipVoice 资产校验也在 `tests/test_zipvoice_gpu_provider.py` 和 `tests/contracts/test_model_asset_integrity_partial_destination_contract.py` 演进：已学习摘要只对相同 repo/revision 的 verified 记录有效。清单换源或换版本后，无预置 SHA 的文件必须重新下载验证；禁止下载时明确失败。现有生产记录包含这些字段并继续复用；缺少来源身份的手写/不完整记录不能作为离线信任依据。清单预置 SHA 不依赖历史来源记录，内容匹配即可离线验收。来源身份与下述安装/互斥边界分别验收。

状态记录读取合同覆盖 JSON 根与 files 类型、非 SHA256 摘要、有效记录共存和大小写兼容：损坏结构视为无已学习记录，无效单项不影响其他有效单项；仍需通过预置 SHA 或指定来源下载建立信任，不能把本地现存内容自动记为可信。

状态写入合同在 `TestZipVoiceStatusAtomicity` 维护：同目录唯一临时文件、关闭后原子替换、序列化/写入/关闭/替换失败时保留旧记录，仅清理本次临时文件。并发写入发布完整快照，最后一次成功替换生效，不合并记录。Windows 可能拒绝同时替换并上报原生访问错误，测试要求至少一次成功且最终记录来自成功写入者；不能吞掉此错误。若文件系统连清理也拒绝，保留原始异常并记录固定清理告警；不承诺断电持久性、强杀后清理或整批资产互斥。

ZipVoice 安装先让 SDK 写入目标所在文件系统的独立暂存目录，校验成功才原子替换；返回外部缓存时复制并校验副本，保留缓存。下载、复制、校验或替换失败不能发布残缺文件。整批失败不提交新状态，但已发布的合格文件保留，重试可复用具有预置 SHA 的文件；不保证整批回滚。`tests/test_zipvoice_asset_process_integration.py` 用真实 spawn 和离线 SDK 替身验证同根目录竞争、独立根目录共享 Vocos、反序清单、锁等待超时和持锁进程退出。父进程必须持有同步对象直到子进程退出，不能依赖 Windows 的句柄生命周期掩盖 Linux 夹具问题。

`ensure()` 按规范化后的资产目标和状态文件路径排序获取 filelock 锁，从读取旧状态持续到提交和最终校验；总锁等待预算复用 `request_timeout_seconds`。锁文件以 `.angevoice.lock` 结尾并保留，不能在释放时删除。边界是同机、支持原生文件锁的 Windows/Linux 文件系统中的合作写入者；不承诺任意网络文件系统、非合作写入或已加载 runtime 的文件版本固定。独立 `status()` 查询不获取整批锁，快速结果仍是 `last_ensure_record`，不是多文件一致性快照。上述替身测试不证明真实模型推理、断电持久性或强杀后的暂存清理。

Manager 加载与失败重试行为继续在 `tests/test_runtime_resilience_and_admin.py` 演进：兼容旧 unload 签名、清理失败保持原加载异常、失败实例移除后重建、provider 忙碌拒绝以及 load=False 不触发加载；依赖方向与 shutdown 合同分别保持独立。

可选路由组装回归在 `tests/test_basic.py` 对新入口、旧回调入口和旧字典回退参数化验证实际 HTTP 鉴权、批量 ZIP 清单、统计及缓存清理。应用 preload/topology 合同只替换组装入口的测试隔离接缝，不改变其生命周期断言。

引擎参数长期行为在 `tests/test_extension_architecture.py` 演进：通用参数覆盖旧字段、空值回退、未知键忽略、整数兼容转换、范围错误及 HTTP/WS 错误响应。非法容器值和溢出不得触发模型加载；冻结文本合同不变。

Provider 决策在 `tests/test_product_model_registry.py` 维护：MOSS 显式提示、配置、CPU/CUDA 别名组合及禁用开关；ZipVoice 与普通设备选择不读取 MOSS 别名。显式禁用 CUDA 的拒绝仍由 Registry 负责。

WS producer 生命周期继续在 `tests/test_ws_cancel_characterization_2615.py` 演进：队列拒绝、异常、取消、正常结束及关闭失败；保留迭代器引用验证显式关闭，并穿过真实 StreamingService 验证底层关闭、模型借用释放、结束通知的顺序。替身模型不证明真实推理或端到端背压。

Kokoro 加载与延迟 English 生命周期统一在 `tests/test_engine_lazy_english_g2p.py` 演进：模型构造、设备迁移、eval、中文 pipeline 的普通异常和中断均保留异常并清理实例引用；覆盖构造中触发 English、成功重试、幂等加载、卸载及最近成功设备信息。权重错误保留提示和 cause，远程构造仍由来源策略准入；这些离线替身不证明真实模型推理或显存立即归还。来源依赖方向与上游 `local_files_only` 历史记录跟随实际构造 owner，冻结 P5 合同不变。

ZipVoice 双 runtime 加载合同在 `tests/test_zipvoice_cpu_runtime.py` 共用离线组件夹具：tokenizer、model、vocoder、eval、feature 构造失败/中断均不发布半成品，随后可重试；CUDA 单独覆盖 checkpoint、model/device 迁移。幂等加载、卸载后再加载、失败重载保持最近成功采样率/device 一并验证。`test_zipvoice_gpu_provider.py` 保留 Engine fallback 与资产准入检查；CUDA 替身通过不能记为真实 GPU 推理通过。

MOSS codec 生命周期在 `test_moss_characterization_2615.py` 覆盖流式/非流式两个实际调用方：OOM、取消、中断与 reset 同时失败时保留原异常；入口 reset 失败不生成，成功生成后的 reset 失败必须传播；后续请求仍重新 reset，并执行 frame callback/尾帧解码。P4 上独立方法与基础 CUDA 运算的探针仅证明该窄边界，不等同完整模型或音质验收。

同一 MOSS 测试文件使用真实线程、Event 和锁验证非隔离 producer：等待 runtime 锁时取消，取得锁后不再准备 prompt；prompt 准备期间取消，不再修改生成配置，后续请求不继承取消状态。关闭消费者仅发出协作停止，正在运行的 producer 继续持锁直到退出；测试显式等待其退出，再验证锁可复用，不能以消费者 done 推断 CUDA/ONNX 已中断。

`test_runtime_resilience_and_admin.py` 以真实 executor 验证重建及强制卸载：旧池尚未启动的 Future 被取消，活动任务仍可完成，新池可接收任务。取消待执行 Future 不代表强停活动线程；受损实例仍由 Manager 丢弃，不得因有新 executor 就重新视为健康。

同一测试文件使用真实线程和可观测的重入锁验证 `current_snapshot()`：读取方等待锁期间当前模型发生切换，取得锁后必须选择新的模型并返回 current=true，且不得创建/加载引擎。该合同保护唯一生命周期 owner 的一致视图；不要求为展示再创建状态服务，也不宣称第三方 metadata 自身线程安全。

GPU 依赖兼容合同继续在 `test_transformers_compatibility_2615.py` 维护：CPU 与 GPU 允许各自锁定已经验证的 Transformers 版本，共享 hub/tokenizers 约束。清单通过不能替代 Docker 构建和真实模型验证。已验证硬件、源码范围与剩余限制见 [依赖安全基线](DEPENDENCY_SECURITY.md)，后续候选必须按变更风险重新验证。

MOSS prompt 文件名兼容继续在 `test_moss_characterization_2615.py` 维护：模拟拒绝安全用途 SHA1 的 provider，执行实际参考音频准备函数，确认非安全路径散列保留非安全命名前缀、生成唯一临时路径且裁剪结果保持。使用真实 Torch 张量与音频 I/O 替身，不作为真实 FIPS 环境或模型推理验收。

Manager 卸载合同覆盖旧签名、force 参数、内部 TypeError 和失败后的计数/待重建状态；运行时异常不可触发二次调用。ZipVoice 路径合同覆盖显式配置、环境变量、内置目录和无效显式路径的优先级，并验证 CPU/CUDA runtime 与只读可用性探测一致且不加载模型。环境变量历史快照保持不变，迁移后的读取者在配置合同中显式映射。

目录查询的状态和音色收集由 Manager 在生命周期锁内完成；路由不再次合并引擎 metadata。行为合同验证目录标识不可被 metadata 覆盖、查询不加载权重，并用另一线程检查锁归属。

参考音频准备通过真实线程和同步屏障验证请求间文件隔离：先完成的请求清理自己的文件后，后完成的请求仍能读取自己的参考音频；写入失败或中断不留下部分文件。音频 I/O 使用替身，不替代模型听感验收。

runtime 配置迁移、过滤和回写与保存/删除共享文件锁。并发合同验证清理不能覆盖随后保存的新值；有效配置读取不要求目录可写，也不创建锁文件。Windows 沿用进程内锁，POSIX 同时使用现有 flock；此项不保证 Windows 跨进程写入或多个内存配置实例自动同步。

子进程 worker 的流合同保留迭代器强引用，验证正常结束、取消、生成异常和队列发送失败时均显式关闭；已有主异常不被普通清理异常覆盖，独立清理失败通过错误通道报告。未知命令必须在创建或加载引擎前返回协议错误。兼容导出不因静态扫描判为未使用就删除；移除仍遵守兼容层台账。
