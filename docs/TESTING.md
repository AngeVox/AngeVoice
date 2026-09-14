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

新增测试按领域和行为命名，历史工单号放在 docstring/证据索引中。优先扩展已有领域合同；本轮不全量搬迁测试、不删除兼容覆盖。`test_text_preparation_boundary_contract.py` 的 CURRENT/FUTURE 命名来自冻结工序，目前 15 项已全绿；该冻结文件保持字节不变，新增进程验证放在独立 integration 模块。

### 领域归属索引

| 领域 | 主要测试入口 | 维护职责 |
| --- | --- | --- |
| 请求文本准备 | `tests/contracts/test_text_preparation_boundary_contract.py`、`tests/test_text_frontend_recovery_tn.py` | service-selected TN、raw/prepared、MOSS runtime flags |
| 文本进程传输 | `tests/test_text_preparation_process_integration.py` | 真实 spawn、父端转发、连续请求无 prepared 状态泄漏；使用替身 runtime |
| 引擎和资源生命周期 | `tests/contracts/test_engine_adapter_conformance_contract.py`、`test_engine_manager_concrete_dependency_contract.py`、`test_shutdown_lifecycle_contract.py` | Adapter 一致性、构造 owner、shutdown admission/drain/retry |
| Worker 协议与失败 | `tests/contracts/test_engine_worker_spec_contract.py`、`test_engine_error_worker_failure_envelope_contract.py`、`test_worker_load_failure_lifecycle_contract.py` | 序列化、code/message、加载事务与恢复 |
| 配置与模型来源 | `tests/contracts/test_model_source_detect_policy_contract.py`、`test_model_source_executor_fallback_contract.py`、`test_model_source_revision_credential_offline_contract.py`，`tests/test_model_source_probe.py`，以及各领域 metadata 合同 | ENV/Admin 投影、优先级、来源选择、HTTP 重定向和下载兼容 |
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

## 覆盖率策略

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

ZipVoice 共用合成路径在 `tests/test_zipvoice_cpu_runtime.py` 中参数化覆盖 CPU/CUDA 包装器，包含参数夹取、参考校验、FLOAT→PCM16、失败清理与 CUDA 专属参数。该文件保留历史名称；替身测试不证明真实 CUDA 推理或音质。provider fallback 继续由 `tests/test_zipvoice_gpu_provider.py` 维护。

Manager 加载与失败重试行为继续在 `tests/test_runtime_resilience_and_admin.py` 演进：兼容旧 unload 签名、清理失败保持原加载异常、失败实例移除后重建、provider 忙碌拒绝以及 load=False 不触发加载；依赖方向与 shutdown 合同分别保持独立。

可选路由组装回归在 `tests/test_basic.py` 对新入口、旧回调入口和旧字典回退参数化验证实际 HTTP 鉴权、批量 ZIP 清单、统计及缓存清理。应用 preload/topology 合同只替换组装入口的测试隔离接缝，不改变其生命周期断言。

引擎参数长期行为在 `tests/test_extension_architecture.py` 演进：通用参数覆盖旧字段、空值回退、未知键忽略、整数兼容转换、范围错误及 HTTP/WS 错误响应。非法容器值和溢出不得触发模型加载；冻结文本合同不变。

Provider 决策在 `tests/test_product_model_registry.py` 维护：MOSS 显式提示、配置、CPU/CUDA 别名组合及禁用开关；ZipVoice 与普通设备选择不读取 MOSS 别名。显式禁用 CUDA 的拒绝仍由 Registry 负责。

WS producer 生命周期继续在 `tests/test_ws_cancel_characterization_2615.py` 演进：队列拒绝、异常、取消、正常结束及关闭失败；保留迭代器引用验证显式关闭，并穿过真实 StreamingService 验证底层关闭、模型借用释放、结束通知的顺序。替身模型不证明真实推理或端到端背压。
