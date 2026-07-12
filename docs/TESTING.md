# AngeVoice 测试与质量门禁

本文定义项目测试层、可复现环境和代码演进必须遵守的运行方式。

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

`requirements/test.lock` 是 Python 3.10–3.12 通用的轻量测试锁；`requirements/test-torch-cpu.lock` 将 Torch 固定为与 Docker CPU/GPU/legacy-gpu 画像一致的 `2.5.1`。更新输入文件后必须重新生成并提交锁文件：

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
| i18n 分域键、占位参数、安全 DOM slot 与 scanner 可见性 | `tests/quality/test_i18n_contract.py`、`test_i18n_runtime.py` |
| 静态资源 content hash、ESM import map 与递归 wheel 打包 | `test_static_asset_manifest.py`、`test_i18n_runtime.py`、`test_studio_model_presentation.py` |

## 覆盖率策略

Python 3.12 当前覆盖率基线约为 72%。CI 下限设为 70%，给跨平台不可达分支保留小幅空间，但任何重构不得主动降低覆盖率。每次有意义的测试提升后，应按实际结果收紧阈值；复杂度热点另外由 `tests/quality/test_architecture_ratchets.py` 执行逐函数只降不升规则。

全局覆盖率不能代替关键路径合同。MOSS、worker、WebSocket 等硬件或并发相关代码即使受平台影响无法获得高行覆盖率，也必须通过明确的协议、取消、超时和资源释放测试保护。

## 浏览器与真实模型 smoke

真实 Chromium/Playwright 基线已验证 Studio 的 `zh-CN -> en` 切换、`localStorage` 持久化和刷新恢复。Playwright 目前不进入默认 CI；涉及前端模块或本地化的变更必须覆盖这三项浏览器行为。Admin 与 API Docs 当前没有完整 i18n，相关改动应补齐对应验收，而不是用错误断言锁住已知缺陷。

涉及静态资源或模块图的改动还必须验证三个页面输出的 import map、全部请求 URL 的 12 位内容哈希、module/CSS 200、无 404/console error/pageerror，并构建 wheel 确认 `static/**/*` 中的新模块确实被打包。

真实模型 smoke 由部署画像运行，不能伪装成无权重单元测试：

```bash
# Kokoro 为必测；MOSS 在可用时运行；ZipVoice 使用已保存 Voice Profile。
ZIPVOICE_SMOKE_VOICE=voice_001 bash scripts/e2e_loop_test.sh http://127.0.0.1:8101 "$API_KEY" 3
```

该脚本的真实模型 smoke contract/harness 已定义：它要求验证 Kokoro HTTP/WebSocket、MOSS 可用 Provider、ZipVoice 已保存音色、取消恢复、可选空闲卸载和短循环稳定性。缺少模型或 ZipVoice Voice Profile 时会明确记为 SKIP，不能报告为通过。定义 harness 不等于已执行或已通过；只有在含真实权重的画像运行后，才能声明真实模型 smoke 已执行或通过。
