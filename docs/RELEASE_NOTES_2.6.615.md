# AngeVoice v2.6.615 Release Notes

## 中文

AngeVoice 2.6.615 是一次安全与可维护性更新，重点修复自有代码安全告警、收敛依赖风险，并拆分核心服务模块以降低后续维护成本。本版本不新增用户词典 CRUD、电子书或批量合成功能，也不改变真实合成接口、WebSocket payload 或模型推理行为。

### 安全更新

- 提示音频临时文件清理改为安全 root 校验，只删除 AngeVoice 内部生成的合法临时文件。
- 限流日志不再记录 API Key、Bearer Token 或 token 片段。
- Studio 默认只在当前页面会话中保存 API Key，刷新后需要重新输入。

### 依赖与安装

- `sentencepiece` 更新到 `>=0.2.1`。
- `modelscope` 更新到 `>=1.27.0`。
- `transformers` 使用 4.53 稳定线，避免引入 5.x 预发布版本风险。
- 修正 ZipVoice 可编辑安装中的 `piper_phonemize` 解析路径，降低普通开发安装失败概率。

### 架构维护

- 拆分 Admin 配置 schema、状态路由、ServiceState、WebSocket 会话、legacy 文本规则与 MOSS 轻量 helper。
- 保持原有外部 API、WebSocket payload、Admin schema、文本 golden 行为和三模型隔离策略。
- MOSS runtime helper 在本版本中保留少量重复实现，以维持轻量 import 边界；后续可在专门的 import 验证后继续去重。

### Docker / fnOS

- Docker 与 fnOS 模板统一使用带 `v` 前缀的版本镜像标签，例如 `maxblack777/angevoice-gpu:v2.6.615`。
- 不回退 `latest`，避免部署时拉取到与发布包不匹配的镜像。
- fnOS manifest、部署文档与版本测试已同步到 2.6.615。

### 兼容性

- 支持 Python 3.10 到 3.12。
- Python 3.13 暂不支持，原因是上游 Kokoro / Misaki 依赖尚未完成兼容。

## English

AngeVoice 2.6.615 is a security and maintainability release. It addresses first-party security findings, reduces dependency risk, and splits several core service modules to make future maintenance safer. This release does not add user dictionary CRUD, ebook features, or batch synthesis features, and it does not change the public synthesis API, WebSocket payloads, or model inference behavior.

### Security

- Prompt-audio temporary cleanup now validates the safe root and only removes valid AngeVoice-generated temporary files.
- Rate-limit logs no longer include API keys, Bearer tokens, or token fragments.
- Studio keeps the API key in the current page session by default; refresh requires re-entry.

### Dependencies and Installation

- `sentencepiece` is updated to `>=0.2.1`.
- `modelscope` is updated to `>=1.27.0`.
- `transformers` uses the 4.53 stable line instead of a 5.x pre-release build.
- ZipVoice editable installs now resolve `piper_phonemize` through pinned wheel references for supported platforms.

### Maintainability

- Admin config schema, status routes, ServiceState, WebSocket session handling, legacy text normalization, and lightweight MOSS helpers were split into smaller modules.
- Existing public APIs, WebSocket payloads, Admin schema output, text golden behavior, and per-model text isolation are preserved.
- A small amount of MOSS runtime helper duplication is intentionally kept in 2.6.615 to preserve lightweight import boundaries; future cleanup can invert legacy helper exports after dedicated import validation.

### Docker / fnOS

- Docker and fnOS templates now use `v`-prefixed versioned image tags, such as `maxblack777/angevoice-gpu:v2.6.615`.
- Templates do not fall back to `latest`, which avoids pulling images that do not match the release package.
- fnOS manifest, deployment docs, and version tests are aligned to 2.6.615.

### Compatibility

- Supported Python versions: 3.10 to 3.12.
- Python 3.13 is not supported yet because upstream Kokoro / Misaki dependencies are not compatible.
