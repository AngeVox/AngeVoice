# AngeVoice 兼容层台账

兼容层用于给调用方提供迁移窗口，不是永久架构。新增兼容层必须同时登记替代接口、维护域、最早移除版本和移除门槛。

当前台账记录既有兼容入口、替代接口和移除条件。共享引擎适配合同将在相关适配层稳定后另行建立；本台账本身不代表共享 `EngineAdapter` 契约已完成。

| ID | 当前兼容层 | 替代接口 | 维护域 | 最早移除 | 移除门槛 |
| --- | --- | --- | --- | --- | --- |
| COMP-001 | `src/kokoro_tts/moss/process_worker.py::MossProcessClient` | `workers.EngineProcessClient(engine_id="moss")` | Worker isolation | 2.8.0 | 仓库内调用清零；发布说明至少提示一个稳定版本；兼容导入测试改为拒绝旧入口 |
| COMP-002 | `moss-nano`、`moss-nano-cpu`、`moss-nano-cuda` 模型别名 | 公共模型 ID `moss` + Provider policy | Model compatibility | 3.0.0 | API/小智/文档调用清零；状态接口持续报告 deprecated alias；完成主版本迁移说明 |
| COMP-003 | `/v1/admin/cache/clear` | `/v1/diagnostics/resources/release` | Admin diagnostics | 3.0.0 | 管理前端和公开文档不再引用；保留一个主版本迁移窗口 |
| COMP-004 | `src/kokoro_tts/admin_config_schema.py` facade | `kokoro_tts.admin_config` package | Configuration | 2.8.0 | 第一方 import 清零；第三方扩展指南更新；facade characterization test 转为新入口合同 |
| COMP-005 | `moss/postprocess.py`、`moss/prompt.py`、`moss/streaming.py` 纯 helper re-export | `moss_runtime.audio/prompt/streaming` | MOSS runtime | 2.8.0 | 第一方 import 清零；MOSS adapter contract 和真实 smoke 通过 |
| COMP-006 | 旧 runtime config 路径迁移 | `ANGEVOICE_RUNTIME_CONFIG_FILE` 指向统一配置目录 | Configuration migration | 3.0.0 | Docker/fnOS 已跨两个稳定版本写入新路径；迁移事件可诊断；文档不再指导旧路径 |
| COMP-007 | `KOKORO_MP3_ENABLED` 映射 FFmpeg 总开关 | `ANGEVOICE_FFMPEG_ENABLED` | Deployment configuration | 3.0.0 | 部署模板和文档清零；启动诊断能提示旧变量；保留一个主版本迁移窗口 |

## 规则

- `DeprecationWarning` 必须能在本台账找到对应源文件和替代入口；
- 不能仅因为内部实现已迁移就删除公开 alias，必须满足表中移除门槛；
- 到达“最早移除”版本不代表自动删除，仍需重新核对使用方和发布说明；
- 兼容层不得继续承载新功能；新能力只加到替代接口；
- 每个主要版本发布前必须逐项更新状态，不能把整张表原样带入下一个主版本。
