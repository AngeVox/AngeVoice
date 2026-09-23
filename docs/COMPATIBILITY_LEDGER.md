# AngeVoice 兼容层台账

兼容层用于给调用方提供迁移窗口，不是永久架构。新增兼容层必须同时登记替代接口、维护域、最早移除版本和移除门槛。

当前台账记录既有兼容入口、替代接口和移除条件。共享 `EngineAdapter`、WorkerSpec、错误传输与 manager 依赖边界已有合同保护；这不等于全部兼容层已满足删除条件。原始架构债的状态见 [架构债务台账](ARCHITECTURE_DEBT.md)。

| ID | 当前兼容层 | 替代接口 | 维护域 | 最早移除 | 移除门槛 |
| --- | --- | --- | --- | --- | --- |
| COMP-001 | `src/kokoro_tts/moss/process_worker.py::MossProcessClient` | `workers.EngineProcessClient(config=cfg, spec=spec)`；spec 为产品 owner 创建的 `EngineWorkerSpec` | Worker isolation | 2.8.0 | 仓库内调用清零；发布说明至少提示一个稳定版本；兼容导入测试改为拒绝旧入口 |
| COMP-002 | `moss-nano`、`moss-nano-cpu`、`moss-nano-cuda` 模型别名 | 公共模型 ID `moss` + Provider policy | Model compatibility | 3.0.0 | API/小智/文档调用清零；状态接口持续报告 deprecated alias；完成主版本迁移说明 |
| COMP-003 | `/v1/admin/cache/clear` | `/v1/diagnostics/resources/release` | Admin diagnostics | 3.0.0 | 管理前端和公开文档不再引用；保留一个主版本迁移窗口 |
| COMP-004 | `src/kokoro_tts/admin_config_schema.py` facade | `kokoro_tts.admin_config` package | Configuration | 2.8.0 | 第一方 import 清零；第三方扩展指南更新；facade characterization test 转为新入口合同 |
| COMP-005 | `moss/postprocess.py`、`moss/streaming.py` 的纯 helper re-export，以及 `moss/prompt.py::prompt_audio_cache_key` re-export | `moss_runtime.audio/streaming/prompt::prompt_audio_cache_key` | MOSS runtime | 2.8.0 | 第一方旧 helper import 清零；MOSS adapter contract 和真实 smoke 通过。`moss/prompt.py` 仍负责参考音频准备与缓存，不属于整模块可删除 shim |
| COMP-006 | 旧 runtime config 路径迁移 | `ANGEVOICE_RUNTIME_CONFIG_FILE` 指向统一配置目录 | Configuration migration | 3.0.0 | Docker/fnOS 已跨两个稳定版本写入新路径；迁移事件可诊断；文档不再指导旧路径 |
| COMP-007 | `KOKORO_MP3_ENABLED` 映射 FFmpeg 总开关 | `ANGEVOICE_FFMPEG_ENABLED` | Deployment configuration | 3.0.0 | 部署模板和文档清零；启动诊断能提示旧变量；保留一个主版本迁移窗口 |
| COMP-008 | service_extras.register_extra_routes 与 ServiceState.as_service_extras_kwargs | register_service_routes 应用组装入口，领域 handler 接收显式依赖 | Route composition | 未排期 | 明确外部使用方与迁移说明后单独确定窗口；新旧 HTTP 行为合同保持，未经独立决策不删除 |

## 规则

- `DeprecationWarning` 必须能在本台账找到对应源文件和替代入口；
- 不能仅因为内部实现已迁移就删除公开 alias，必须满足表中移除门槛；
- 到达“最早移除”版本不代表自动删除，仍需重新核对使用方和发布说明；
- 兼容层不得继续承载新功能；新能力只加到替代接口；
- 每个主要版本发布前必须逐项更新状态，不能把整张表原样带入下一个主版本。

## 现状核对（2026-09-23，2.6.616 工作树）

| ID | 当前判断 |
| --- | --- |
| COMP-001 | 生产路径已使用通用 process client；旧类仍被兼容测试导入，未到 2.8.0 和公告窗口。 |
| COMP-002 | 配置归一化、模型解析和公开文档仍识别旧 ID；未到 3.0.0。 |
| COMP-003 | 旧 HTTP 路由和兼容响应仍存在；未到 3.0.0。 |
| COMP-004 | 生产代码已改从 `kokoro_tts.admin_config` 导入；旧 facade 继续服务历史导入测试和外部调用，未到 2.8.0。 |
| COMP-005 | MOSS 引擎已直接使用部分 `moss_runtime` helper，但 `moss` 包导出仍供调用方使用；`moss/prompt.py` 还拥有实际参考音频处理逻辑，不能整模块删除。 |
| COMP-006 | 部署模板指向新目录，旧路径读取迁移仍在；尚无跨两个稳定版本的迁移证据。 |
| COMP-007 | 旧环境变量仍见于模板、文档和 Admin 帮助；未到 3.0.0。 |
| COMP-008 | 主应用使用 `register_service_routes`，旧入口有行为测试；外部使用方与移除窗口未确定。 |

本次仅清理第一方对 COMP-004 的内部依赖并校正 COMP-005 的范围。其余兼容入口继续保留；下一次版本评估应重新核对使用方与公告，而非按本次快照自动删除。
