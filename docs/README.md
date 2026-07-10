# AngeVoice 文档

AngeVoice 提供三个稳定产品模型入口：`Kokoro v1.1 Chinese`、`MOSS-TTS-Nano` 与 `ZipVoice`。CPU、CUDA 与自动回退等运行信息在状态与诊断中单独展示。2.6.615 聚焦安全、依赖与可维护性：强化 API Key 处理、提示音频临时文件清理、Docker/fnOS 版本化镜像，以及核心服务模块边界。

## 使用与部署

| 文档 | 内容 |
| --- | --- |
| [API 参考](API_REFERENCE.md) | HTTP、WebSocket、Voice Profile、管理接口与认证 |
| [Docker 部署画像](DEPLOYMENT_PROFILES.md) | CPU、标准 GPU 与 Legacy GPU 兼容模式 |
| [fnOS / FPK 部署](FNOS_FPK.md) | 飞牛系统安装、运行模式与持久化目录 |
| [安全说明](SECURITY.md) | 默认首次登录、改密、API Key 与上传安全 |
| [故障排查](TROUBLESHOOTING.md) | 启动、模型、音频质量与运行状态排错 |
| [模型运行时](MODEL_RUNTIME.md) | 三模型定位、Provider 与流式行为 |
| [服务画像](SERVICE_PROFILES.md) | NAS/GPU 配置建议与资源策略 |
| [MOSS 音频质量](MOSS_AUDIO_QUALITY.md) | MOSS 参数与音频听感排查 |

## 开发与集成

| 文档 | 内容 |
| --- | --- |
| [架构说明](ARCHITECTURE.md) | 服务结构、统一请求契约与资源管理 |
| [测试与质量门禁](TESTING.md) | 可复现测试环境、测试分层、覆盖率和当前行为保护映射 |
| [兼容层台账](COMPATIBILITY_LEDGER.md) | 旧入口、替代接口、维护域和移除门槛 |
| [新增模型 Adapter 指南](NEW_MODEL_ADAPTER_GUIDE.md) | 新模型接入的扩展接口与能力注册 |
| [阅读器后端接入](ANGE_READER_BACKEND_ADAPTER.md) | 面向阅读器/第三方客户端的调用方式 |
| [许可证合规](LICENSE_COMPLIANCE.md) | 模型与第三方组件许可证说明 |

## 版本信息

版本变更记录见仓库根目录 [CHANGELOG.md](../CHANGELOG.md)。
