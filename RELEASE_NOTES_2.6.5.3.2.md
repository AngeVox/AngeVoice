# AngeVoice 2.6.5.3.2 Release Notes

本版本包含 MOSS ONNX 与 Kokoro 音色列表紧急修复：切换 MOSS 时若统一模型目录存在但缺少 `browser_poc_manifest.json` 或真实模型资产，会自动尝试从 `MOSS_MODELSCOPE_REPO` 下载补全；下载后的 `*.data` 大权重会被正确识别。同时修复 Hugging Face 缓存快照中的 Kokoro 音色没有出现在前端音色库的问题。

本版本重点集成 TTS 后端完整包、修复模型目录混乱和 Kokoro 音色 LFS 指针刷屏问题，并优化 Docker/NAS 下的模型持久化体验。

## TTS 后端新功能

- 新增 `/v1/tts/capabilities` 端点：查询模型能力、可用格式、音色详情和前端提示。
- `/v1/audio/speech` 支持 `response_encoding=base64`，返回 JSON（含 `audio` 裸 base64、`audio_base64` data URL）。
- `/v1/audio/voices` 支持 `?detail=true` 返回音色性别、显示名等详情。
- `TTSRequest` 新增 `emotion`、`emotion_strength`、`style_prompt` 保留字段，预留未来情感/风格控制。
- 新增 `docs/ANGE_READER_BACKEND_ADAPTER.md` 阅读器接入指南。

## 安全加固

- Bearer token 解析要求空白分隔符，防止 `Bearerxxx` 误通过。

## 重点变化

- 统一模型根目录为 `models/`，Docker 内路径为 `/app/models`。
- Kokoro 推荐目录：`models/models--hexgrad--Kokoro-82M-v1.1-zh`。
- MOSS ONNX 推荐目录：`models/MOSS-TTS-Nano-100M-ONNX`。
- Hugging Face 缓存默认写入 `/app/models`，ModelScope 缓存默认写入 `/app/models/modelscope-cache`。
- Docker Compose 不再单独挂载 `hf_cache` 和 `moss_models`。
- 安装脚本会在新目录为空时尝试迁移旧 `hf_cache` 和 `moss_models`。
- Kokoro 音色校验改为优先识别 PyTorch 文件头，真实小型 `.pt` 不会被误判；LFS 指针仍会被跳过且同一路径只 warning 一次。
- 新增启动横幅，输出版本、监听地址、启用模型和模型目录。

## 升级建议

升级后目录建议为：

```text
models/
├── models--hexgrad--Kokoro-82M-v1.1-zh/
├── MOSS-TTS-Nano-100M-ONNX/
├── modelscope-cache/
└── .hf/
```

如旧版本已有 `hf_cache` 或 `moss_models`，可直接运行：

```bash
AngeVoice
```

选择安装/更新，脚本会尝试温和迁移。迁移失败也不会影响启动，服务会按需重新下载模型。

## 代码质量收尾

本轮在统一模型目录基础上补做了静态审查反馈修复：

- 统一 logging 懒求值写法，避免 f-string logging 混用。
- 拆开 `EngineManager` 的模型快照字典，避免运行时 metadata 静默覆盖基础身份字段。
- 金额文本规范化支持十亿以上金额。
- `get_voices()` 增加目录 mtime 缓存，减少轮询时的文件系统扫描。
- 缓存统计与读取路径更一致。
- 新增专项回归测试，当前轻量测试为 132 passed。


## 最终收尾修复

在代码质量审查后，最终版补齐了以下一致性和边界修复：

- `.env.prod`、`.env.staging`、根 `.env.example` 与 `docker/angevoice.env` 的 MOSS 参数完全对齐，避免生产/暂存配置漂移。
- 多 worker 启动时会正确继承 `ANGEVOICE_IDLE_UNLOAD_CURRENT`。
- `ensure_moss_model_dir()` 增加真实模型文件校验，不再把只有 Git LFS 指针或占位文件的非空目录视为有效 MOSS 模型目录。
- `100%` 等百分比文本改为自然读法。
- `docker/entrypoint.sh` 使用 `set -euo pipefail`。
- `docker/.env.example` 去除重复变量，并补充后台默认密码的公网安全提示。
- `README_EN.md` 补齐中文版已有的 MOSS 音频后处理、实时流式、限流和队列配置说明。
- `V2_5_FEATURES.md`、`SERVICE_PROFILES.md` 等文档中的旧默认值已对齐到 2.6.5.3.2。
## 最终追加修复

在二次配置审查后，最终包继续补齐以下细节：

- 多 worker 环境导出补齐 `KOKORO_TTS_REQUEST_MAX_BYTES` 与 `KOKORO_VOICE_UPLOAD_MAX_BYTES`。
- `.env.prod`、`.env.staging`、根 `.env.example` 补齐 MOSS 默认音色、WeText、文本标准化、CUDA 自检和质量闸门变量说明。
- `EngineManager.get_engine()` 加载失败后的旧签名 `unload()` fallback 增加异常保护，避免清理失败覆盖原始加载错误。
- worker 环境变量测试改为覆盖 `config_env.py` 的运行时配置集合，防止后续新增变量漏传。
- `test_text_rules_false_not_reported_as_enabled` 不再依赖真实 MOSS runtime 依赖，适合轻量 CI 环境。
- 本轮新增和触碰代码注释统一使用中文说明。



## MOSS ONNX 紧急修复

- `ensure_moss_model_dir()` 不再把空目录、README-only 目录、Git LFS 指针目录交给官方 runtime。
- MOSS 资产校验支持官方 ModelScope 包的 `*.data` 大权重，避免下载完成后仍误判失败。
- 默认使用 `MOSS_MODELSCOPE_REPO=openmoss/MOSS-TTS-Nano-100M-ONNX` 兜底下载 MOSS ONNX 资产。
- Kokoro 音色列表会扫描 `models--hexgrad--Kokoro-82M-v1.1-zh/snapshots/<sha>/voices`，修复前端音色库显示 0 的问题。
- 新增可选 `MOSS_HF_REPO`，仅在用户显式配置后尝试 Hugging Face MOSS ONNX 下载。
- 新增回归测试覆盖空目录自动下载和 README-only 目录拒绝。
